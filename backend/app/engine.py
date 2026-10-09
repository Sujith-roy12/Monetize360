"""Pure evaluator: no database, wall clock, network, or industry branches."""
from datetime import date,datetime
from decimal import Decimal,ROUND_HALF_UP,ROUND_CEILING,ROUND_FLOOR,localcontext,DecimalException
import hashlib,json
from .schema import Strategy,Expr,Condition,decimal,check_value
ENGINE_VERSION='2.0.0'

class PricingError(ValueError):
    """Context or strategy has no valid pricing result."""

def dump(value):
    if isinstance(value,Decimal):return str(value)
    if isinstance(value,(datetime,date)):return value.isoformat()
    if isinstance(value,dict):return {k:dump(v) for k,v in value.items()}
    if isinstance(value,list):return [dump(v) for v in value]
    return value

def config_hash(s):return hashlib.sha256(json.dumps(s.model_dump(mode='json'),sort_keys=True,separators=(',',':')).encode()).hexdigest()

def resolve_context(s,raw):
    extra=set(raw)-{a.key for a in s.attributes}
    if extra:raise PricingError('Unknown input attributes: '+', '.join(sorted(extra)))
    out={};defaults=[]
    for a in s.attributes:
        if a.key in raw:v=raw[a.key]
        elif a.default is not None:v=a.default;defaults.append(a.key)
        else:raise PricingError('Missing required attribute: '+a.key)
        try:out[a.key]=check_value(a,v)
        except ValueError as e:raise PricingError(str(e)) from e
    return out,defaults

def expression(e:Expr,ctx):
    if e.op=='const':return decimal(e.value)
    if e.op=='field':return decimal(ctx[e.field])
    a=[expression(v,ctx) for v in e.args]
    if e.op=='add':v=sum(a,Decimal(0))
    elif e.op=='subtract':v=a[0]-a[1]
    elif e.op=='multiply':
        v=Decimal(1)
        for n in a:v*=n
    elif e.op=='divide':
        if a[1]==0:raise PricingError('Division by zero in pricing expression')
        v=a[0]/a[1]
    elif e.op=='min':v=min(a)
    else:v=max(a)
    return decimal(v)

def condition(c:Condition,ctx):
    if c.op in ['all','any','not']:
        children=[condition(x,ctx) for x in c.children]
        hits=[x['matched'] for x in children]
        matched=all(hits) if c.op=='all' else any(hits) if c.op=='any' else not hits[0]
        return {'op':c.op,'matched':matched,'children':children}
    left=ctx[c.field]
    def cast(v):
        if isinstance(left,Decimal):return decimal(v)
        if isinstance(left,date):return date.fromisoformat(v)
        return v
    right=[cast(v) for v in c.value] if c.op in ['in','between'] else cast(c.value)
    comparisons={'eq':lambda:left==right,'ne':lambda:left!=right,'gt':lambda:left>right,'gte':lambda:left>=right,'lt':lambda:left<right,'lte':lambda:left<=right,'in':lambda:left in right,'between':lambda:right[0]<=left<=right[1]}
    return {'field':c.field,'op':c.op,'actual':dump(left),'expected':dump(right),'matched':comparisons[c.op]()}

def evaluate(s:Strategy,base_rate,raw,at:datetime,disabled_rule_ids=()):
    if at.tzinfo is None:raise PricingError('Evaluation timestamp must include timezone')
    unknown=set(disabled_rule_ids)-{r.id for r in s.rules}
    if unknown:raise PricingError('Unknown disabled rule ID')
    try:
        with localcontext() as decimal_context:
            decimal_context.prec=28
            return _evaluate(s,base_rate,raw,at,set(disabled_rule_ids))
    except (ValueError,KeyError,DecimalException,TypeError) as e:
        if isinstance(e,PricingError):raise
        raise PricingError(str(e)) from e

def _evaluate(s,base_rate,raw,at,disabled):
    ctx,defaulted=resolve_context(s,raw);ctx['base_rate']=decimal(base_rate)
    if ctx['base_rate']<0:raise PricingError('Negative base rate')
    base=expression(s.base,ctx)
    if base<0:raise PricingError('Negative base amount')
    ctx['base_amount']=base;ctx['subtotal']=base
    trace=[{'id':'base','name':'Base calculation','status':'applied','before':'0','after':str(base),'delta':str(base),'expression':s.base.model_dump(mode='json')}]
    groups={}
    for r in sorted(s.rules,key=lambda r:(r.priority,r.id)):
        before=ctx['subtotal'];reason=None;check=None
        if not r.enabled or r.id in disabled:reason='disabled'
        elif r.starts_at and at<r.starts_at:reason='not_yet_effective'
        elif r.ends_at and at>=r.ends_at:reason='expired'
        else:
            check=condition(r.when,ctx)
            if not check['matched']:reason='condition_not_met'
            elif r.exclusive_group and r.exclusive_group in groups:reason='exclusive_group_won_by:'+groups[r.exclusive_group]
        item={'id':r.id,'name':r.name,'priority':r.priority,'before':str(before),'after':str(before),'delta':'0','status':'skipped' if reason else 'applied','reason':reason,'condition':check}
        if not reason:
            amount=expression(r.action.value,ctx);basis=ctx[r.action.basis]
            if r.action.type=='percent':after=before+basis*amount/100
            elif r.action.type=='add':after=before+amount
            elif r.action.type=='multiply':after=before*amount
            elif r.action.type=='basis_points':after=before+amount/100
            else:after=amount
            after=decimal(after);ctx['subtotal']=after
            item.update(after=str(after),delta=str(after-before),action=r.action.type,value=str(amount),basis=r.action.basis,basis_value=str(basis))
            if r.exclusive_group:groups[r.exclusive_group]=r.id
        trace.append(item)
    lo=max(Decimal(0),expression(s.constraints.minimum,ctx)) if s.constraints.minimum else Decimal(0)
    hi=expression(s.constraints.maximum,ctx) if s.constraints.maximum else Decimal('1e15')
    step=decimal(s.constraints.round_to)
    low=(lo/step).to_integral_value(rounding=ROUND_CEILING)*step
    high=(hi/step).to_integral_value(rounding=ROUND_FLOOR)*step
    if low>high:raise PricingError('No feasible price: bounds and rounding conflict')
    before=ctx['subtotal'];bounded=min(high,max(low,before))
    trace.append({'id':'constraints','name':'Hard bounds','status':'applied' if before!=bounded else 'checked','before':str(before),'after':str(bounded),'delta':str(bounded-before),'minimum':str(lo),'maximum':str(hi) if s.constraints.maximum else None})
    price=(bounded/step).to_integral_value(rounding=ROUND_HALF_UP)*step
    trace.append({'id':'rounding','name':'Rounding','status':'applied' if price!=bounded else 'checked','before':str(bounded),'after':str(price),'delta':str(price-bounded),'step':str(step)})
    if not low<=price<=high:raise PricingError('Final constraint validation failed')
    return {'strategy_id':s.id,'strategy_name':s.name,'output_type':s.output_type,'currency':s.currency,'unit':s.unit,'base_amount':str(base),'final_price':str(price),'trace':trace,'resolved_context':dump({k:v for k,v in ctx.items() if k not in ['base_amount','subtotal']}),'defaulted_attributes':defaulted,'evaluated_at':at.isoformat(),'engine_version':ENGINE_VERSION,'config_hash':config_hash(s),'disabled_rule_ids':sorted(disabled)}

def run_scenarios(s,scenarios,at,disabled=()):
    results=[]
    for case in scenarios:
        try:
            result=evaluate(s,case.base_rate,case.context,at,disabled)
            passed=False if case.expected_error else (decimal(result['final_price'])==decimal(case.expected_price) if case.expected_price is not None else None)
            results.append({'name':case.name,'result':result,'error':None,'expected_price':case.expected_price,'passed':passed})
        except PricingError as e:
            results.append({'name':case.name,'result':None,'error':str(e),'expected_price':case.expected_price,'passed':bool(case.expected_error)})
    return results

def validation_report(s,at):
    cases=run_scenarios(s,s.scenarios,at)
    labelled=[c for c in cases if c['passed'] is not None]
    failed=[c for c in cases if c['passed'] is False or (c['error'] and not c['passed'])]
    return {'valid':not failed,'case_count':len(cases),'labelled_count':len(labelled),'successful_price_tests':sum(c['passed'] is True and c['result'] is not None for c in cases),'passed_count':sum(c['passed'] is True for c in cases),'failed_count':len(failed),'results':cases,'config_hash':config_hash(s),'evaluated_at':at.isoformat(),'scope':'Structural validation plus configured scenarios; not exhaustive proof over every possible input.'}
