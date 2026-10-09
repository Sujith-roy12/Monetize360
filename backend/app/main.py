import hashlib,json,os,secrets,time
from contextlib import asynccontextmanager
from datetime import datetime,timezone
from pathlib import Path
import yaml
from fastapi import FastAPI,Depends,Header,HTTPException,Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select,func,text
from sqlalchemy.exc import IntegrityError
from .db import Base,engine,Session,StrategyRecord,Version,Product,Decision,Simulation,Audit
from .schema import Strategy,ProductInput,PriceRequest,SimRequest,CompareRequest,VersionRequest,ValidationRequest,CopilotRequest,check_value,decimal
from .engine import evaluate,validation_report,run_scenarios,config_hash,PricingError,ENGINE_VERSION
from .copilot import propose
ROOT=Path(__file__).resolve().parents[2]
def now():return datetime.now(timezone.utc)
def db():
    with Session() as session:yield session

def role(x_admin_token:str=Header(default='')):
    return 'publisher'
def publisher(actor=Depends(role)):
    return 'publisher'

def log(s,actor,action,entity,detail):s.add(Audit(actor=actor,action=action,entity=entity,detail=detail))
def get_version(s,id,version=None):
    strategy=s.get(StrategyRecord,id)
    if not strategy:raise HTTPException(404,'Unknown strategy')
    version=version if version is not None else strategy.active_version
    row=s.scalar(select(Version).where(Version.strategy_id==id,Version.version==version))
    if not row:raise HTTPException(409,'No matching version; publish a strategy first')
    return Strategy.model_validate(row.config),row

def check_defaults(config,defaults):
    attrs={a.key:a for a in config.attributes}
    if set(defaults)-set(attrs):raise HTTPException(422,'Product defaults reference unknown attributes')
    try:
        for k,v in defaults.items():check_value(attrs[k],v)
    except ValueError as e:raise HTTPException(422,str(e)) from e

def run(config,base_rate,context,at,disabled=()):
    started=time.perf_counter()
    try:r=evaluate(config,base_rate,context,at,disabled)
    except PricingError as e:raise HTTPException(422,str(e)) from e
    r['engine_latency_ms']=round((time.perf_counter()-started)*1000,3)
    return r

@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    with Session() as s:
        for path in sorted((ROOT/'configs').glob('*.yaml')):
            payload=yaml.safe_load(path.read_text());config=Strategy.model_validate(payload['strategy'])
            if not s.get(StrategyRecord,config.id):
                report=validation_report(config,now())
                if not report['valid'] or report['labelled_count']==0:raise RuntimeError('Invalid seed scenarios: '+config.id)
                s.add(StrategyRecord(id=config.id,name=config.name,active_version=1));s.flush()
                s.add(Version(strategy_id=config.id,version=1,config=config.model_dump(mode='json'),config_hash=config_hash(config),status='published',validation=report))
                for item in payload['products']:
                    p=ProductInput.model_validate(item);check_defaults(config,p.defaults)
                    s.add(Product(id=p.id,strategy_id=p.strategy_id,data=p.model_dump(mode='json')))
                log(s,'system','seed',config.id,{'version':1})
        s.commit()
    yield

app=FastAPI(title='Monetize360 V2',version=ENGINE_VERSION,lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=os.getenv('CORS_ORIGINS','http://localhost:5173,http://127.0.0.1:5173,http://localhost:8080').split(','),allow_methods=['GET','POST','PUT'],allow_headers=['Content-Type','X-Admin-Token','Idempotency-Key'])

@app.get('/health')
def health(s=Depends(db)):
    s.execute(text('SELECT 1'))
    return {'status':'ok','engine_version':ENGINE_VERSION,'database':engine.dialect.name,'ai_configured':bool(os.getenv('GEMINI_API_KEY'))}

@app.get('/auth/me')
def me(actor=Depends(role)):return {'role':actor}

@app.get('/domains')
@app.get('/strategies')
def strategies(s=Depends(db)):
    result=[]
    for d in s.scalars(select(StrategyRecord).order_by(StrategyRecord.id)):
        latest=s.scalar(select(Version).where(Version.strategy_id==d.id).order_by(Version.version.desc()))
        result.append({'id':d.id,'name':d.name,'active_version':d.active_version,'latest_version':latest.version,'config':latest.config})
    return result

@app.post('/domains',status_code=201)
@app.post('/strategies',status_code=201)
def create_strategy(config:Strategy,s=Depends(db),actor=Depends(role)):
    if s.get(StrategyRecord,config.id):raise HTTPException(409,'Strategy exists; save a new version')
    s.add(StrategyRecord(id=config.id,name=config.name,active_version=None));s.flush()
    s.add(Version(strategy_id=config.id,version=1,config=config.model_dump(mode='json'),config_hash=config_hash(config)))
    log(s,actor,'create_draft',config.id,{'version':1})
    try:s.commit()
    except IntegrityError as e:s.rollback();raise HTTPException(409,'Concurrent create; reload strategies') from e
    return {'id':config.id,'version':1,'status':'draft'}

@app.get('/strategies/{id}/versions')
def versions(id:str,s=Depends(db)):
    return [{'version':r.version,'status':r.status,'config':r.config,'validation':r.validation,'config_hash':r.config_hash} for r in s.scalars(select(Version).where(Version.strategy_id==id).order_by(Version.version.desc()))]

@app.post('/strategies/{id}/versions',status_code=201)
def save_version(id:str,config:Strategy,s=Depends(db),actor=Depends(role)):
    d=s.scalar(select(StrategyRecord).where(StrategyRecord.id==id).with_for_update())
    if not d:raise HTTPException(404,'Unknown strategy')
    if id!=config.id:raise HTTPException(422,'Strategy identity cannot change')
    previous=s.scalar(select(Version).where(Version.strategy_id==id).order_by(Version.version.desc()))
    for field in ['currency','output_type','unit']:
        if previous.config[field]!=getattr(config,field):raise HTTPException(422,'Output currency/type/unit is immutable within a strategy; clone as new strategy')
    version=previous.version+1
    s.add(Version(strategy_id=id,version=version,config=config.model_dump(mode='json'),config_hash=config_hash(config)))
    log(s,actor,'create_draft',id,{'version':version})
    try:s.commit()
    except IntegrityError as e:s.rollback();raise HTTPException(409,'Concurrent save; reload versions') from e
    return {'id':id,'version':version,'status':'draft'}

@app.post('/strategies/validate')
def validate(body:ValidationRequest):return {**validation_report(body.config,body.at or now()),'config':body.config.model_dump(mode='json')}

@app.post('/strategies/{id}/approve')
def approve(id:str,body:VersionRequest,s=Depends(db),actor=Depends(publisher)):
    config,v=get_version(s,id,body.version)
    if v.status=='published':raise HTTPException(409,'Version is already published')
    report=validation_report(config,now())
    if not report['valid'] or report['successful_price_tests']==0:raise HTTPException(422,{'message':'Approval requires at least one passing expected-price scenario and all configured tests passing','report':report})
    v.status='approved';v.validation=report;log(s,actor,'approve',id,{'version':v.version,'config_hash':v.config_hash});s.commit()
    return {'status':'approved','version':v.version,'report':report}

@app.post('/strategies/{id}/publish')
def publish(id:str,body:VersionRequest,s=Depends(db),actor=Depends(publisher)):
    config,v=get_version(s,id,body.version)
    if v.status not in ['approved','published']:raise HTTPException(409,'Approve the draft before publication')
    report=validation_report(config,now())
    if not report['valid'] or not report['successful_price_tests']:raise HTTPException(422,'Scenario tests no longer pass at publication time')
    for p in s.scalars(select(Product).where(Product.strategy_id==id)):check_defaults(config,p.data['defaults'])
    d=s.scalar(select(StrategyRecord).where(StrategyRecord.id==id).with_for_update());old=d.active_version
    d.active_version=v.version;d.name=config.name;v.status='published';v.validation=report
    log(s,actor,'publish_or_rollback',id,{'from':old,'to':v.version,'config_hash':v.config_hash});s.commit()
    return {'active_version':v.version,'previous_version':old}

@app.get('/products')
def products(s=Depends(db)):
    result=[]
    for p in s.scalars(select(Product).order_by(Product.id)):
        d=s.get(StrategyRecord,p.strategy_id)
        config=None
        if d.active_version:config=get_version(s,p.strategy_id)[0].model_dump(mode='json')
        result.append({**p.data,'active_version':d.active_version,'config':config})
    return result

@app.post('/products',status_code=201)
def create_product(body:ProductInput,s=Depends(db),actor=Depends(role)):
    if s.get(Product,body.id):raise HTTPException(409,'Product already exists')
    d=s.get(StrategyRecord,body.strategy_id)
    if not d:raise HTTPException(404,'Unknown strategy')
    latest=s.scalar(select(Version).where(Version.strategy_id==d.id).order_by(Version.version.desc()))
    config=get_version(s,d.id,d.active_version or latest.version)[0];check_defaults(config,body.defaults)
    s.add(Product(id=body.id,strategy_id=body.strategy_id,data=body.model_dump(mode='json')))
    log(s,actor,'create_product',body.id,body.model_dump(mode='json'));s.commit();return body

@app.put('/products/{id}')
def update_product(id:str,body:ProductInput,s=Depends(db),actor=Depends(role)):
    p=s.get(Product,id)
    if not p:raise HTTPException(404,'Unknown product')
    if id!=body.id:raise HTTPException(422,'Product identity cannot change')
    config,v=get_version(s,body.strategy_id);check_defaults(config,body.defaults)
    p.strategy_id=body.strategy_id;p.data=body.model_dump(mode='json');log(s,actor,'update_product',id,p.data);s.commit();return body

@app.post('/pricing/calculate')
def calculate(body:PriceRequest,idempotency_key:str|None=Header(default=None,max_length=120),s=Depends(db)):
    request=body.model_dump(mode='json');digest=hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest()
    def existing():
        row=s.scalar(select(Decision).where(Decision.idempotency_key==idempotency_key)) if idempotency_key else None
        if row and row.request_hash!=digest:raise HTTPException(409,'Idempotency key belongs to a different request')
        return {**row.result,'decision_id':row.id} if row else None
    found=existing()
    if found:return found
    p=s.get(Product,body.product_id)
    if not p:raise HTTPException(404,'Unknown product')
    config,v=get_version(s,p.strategy_id)
    if v.status!='published':raise HTTPException(409,'Strategy is not published')
    context={**p.data['defaults'],**body.context}
    result=run(config,p.data['base_rate'],context,now());result.update(version=v.version,product_id=p.id,product_name=p.data['name'])
    row=Decision(product_id=p.id,strategy_id=p.strategy_id,version=v.version,product_snapshot=p.data,request=request,result=result,request_hash=digest,idempotency_key=idempotency_key)
    s.add(row)
    try:s.commit()
    except IntegrityError as e:
        s.rollback();found=existing()
        if found:return found
        raise HTTPException(409,'Concurrent decision conflict') from e
    return {**result,'decision_id':row.id}

@app.post('/pricing/simulate')
def simulate(body:SimRequest,s=Depends(db)):
    config,v=get_version(s,body.strategy_id,body.version);at=body.at or now()
    results=run_scenarios(config,body.scenarios,at,body.disabled_rule_ids)
    result={'results':results,'version':v.version,'config_hash':v.config_hash,'evaluated_at':at.isoformat(),'persisted_as_transactions':False}
    row=Simulation(request=body.model_dump(mode='json'),result=result);s.add(row);s.commit()
    return {**result,'simulation_id':row.id}

@app.post('/pricing/compare')
def compare(body:CompareRequest,s=Depends(db)):
    new,v=get_version(s,body.strategy_id,body.version);old,baseline=get_version(s,body.strategy_id,body.baseline_version);at=body.at or now()
    a=run_scenarios(old,body.scenarios,at);b=run_scenarios(new,body.scenarios,at,body.disabled_rule_ids)
    rows=[]
    for x,y in zip(a,b):
        delta=str(decimal(y['result']['final_price'])-decimal(x['result']['final_price'])) if x['result'] and y['result'] else None
        rows.append({'name':x['name'],'baseline':x,'candidate':y,'price_delta':delta})
    result={'rows':rows,'changed_count':sum(r['price_delta'] is not None and decimal(r['price_delta'])!=0 for r in rows),'error_count':sum(r['price_delta'] is None for r in rows),'scope':'Price differences only; not revenue uplift. Both versions use the same supplied scenario context.','evaluated_at':at.isoformat()}
    row=Simulation(request=body.model_dump(mode='json'),result=result);s.add(row);s.commit();return {**result,'simulation_id':row.id}

@app.get('/pricing/history')
def history(product_id:str|None=None,limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0),s=Depends(db)):
    q=select(Decision)
    if product_id:q=q.where(Decision.product_id==product_id)
    total=s.scalar(select(func.count()).select_from(q.subquery()))
    rows=s.scalars(q.order_by(Decision.id.desc()).offset(offset).limit(limit))
    return {'total':total,'items':[{'id':r.id,'request':r.request,'product_snapshot':r.product_snapshot,'result':r.result} for r in rows]}

@app.post('/pricing/history/{id}/replay')
def replay(id:int,s=Depends(db)):
    r=s.get(Decision,id)
    if not r:raise HTTPException(404,'Unknown decision')
    if r.result['engine_version']!=ENGINE_VERSION:raise HTTPException(409,'Historical engine version is required for exact replay')
    config,v=get_version(s,r.strategy_id,r.version)
    if config_hash(config)!=r.result['config_hash']:raise HTTPException(409,'Historical configuration hash mismatch')
    ctx={**r.product_snapshot['defaults'],**r.request['context']}
    result=run(config,r.product_snapshot['base_rate'],ctx,datetime.fromisoformat(r.result['evaluated_at']))
    return {'matches':result['final_price']==r.result['final_price'] and result['trace']==r.result['trace'],'original':r.result,'replayed':result}

@app.get('/analytics')
def analytics(s=Depends(db)):
    rows=list(s.scalars(select(Decision).order_by(Decision.id.desc()).limit(1000)));times=sorted(r.result['engine_latency_ms'] for r in rows)
    by={}
    for r in rows:by[r.strategy_id]=by.get(r.strategy_id,0)+1
    return {'decisions':s.scalar(select(func.count(Decision.id))),'products':s.scalar(select(func.count(Product.id))),'strategies':s.scalar(select(func.count(StrategyRecord.id))),'simulations':s.scalar(select(func.count(Simulation.id))),'window':len(rows),'p95_engine_ms':times[min(len(times)-1,int(.95*len(times)))] if times else None,'by_strategy':[{'strategy':k,'decisions':v} for k,v in by.items()],'note':'Observed calls only. No real sales or revenue tracked.'}

@app.get('/audit')
def audits(s=Depends(db)):
    return [{'id':r.id,'actor':r.actor,'action':r.action,'entity':r.entity,'detail':r.detail,'at':r.created_at.isoformat()} for r in s.scalars(select(Audit).order_by(Audit.id.desc()).limit(100))]

@app.post('/assistant/draft')
async def ai_draft(body:CopilotRequest,actor=Depends(role)):return await propose(body.instruction,body.config)
