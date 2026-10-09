from __future__ import annotations
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
import re

class Strict(BaseModel):
    model_config=ConfigDict(extra="forbid",allow_inf_nan=False)

def decimal(value):
    if isinstance(value,bool): raise ValueError("Boolean is not a number")
    try: d=Decimal(str(value))
    except (InvalidOperation,ValueError,TypeError) as e: raise ValueError("Expected a finite decimal number") from e
    if not d.is_finite() or abs(d)>Decimal('1e15'): raise ValueError("Number must be finite and at most 1e15 in magnitude")
    return d

class Attribute(Strict):
    key:str=Field(pattern=r"^[a-z][a-z0-9_]{0,49}$")
    label:str=Field(min_length=1,max_length=80)
    type:Literal['number','integer','category','boolean','date']='number'
    required:bool=True
    default:Any=None
    minimum:float | None=None
    maximum:float | None=None
    options:list[str]=Field(default_factory=list,max_length=100)
    @model_validator(mode='after')
    def valid(self):
        if self.key in ['base_rate','base_amount','subtotal']:raise ValueError('Reserved attribute name')
        if self.minimum is not None and self.maximum is not None and self.minimum>self.maximum:raise ValueError('Attribute minimum exceeds maximum')
        if self.type=='category' and (not self.options or len(set(self.options))!=len(self.options)):raise ValueError('Categories need unique options')
        if self.default is not None:check_value(self,self.default)
        if not self.required and self.default is None:raise ValueError('Optional attributes require an explicit default')
        return self

def check_value(a:Attribute,v):
    if a.type in ['number','integer']:
        if isinstance(v,str) or isinstance(v,bool) or not isinstance(v,(int,float,Decimal)):raise ValueError(f'{a.key}: expected numeric JSON value')
        d=decimal(v)
        if a.type=='integer' and d!=d.to_integral_value():raise ValueError(f'{a.key}: expected an integer')
        if a.minimum is not None and d<decimal(a.minimum):raise ValueError(f'{a.key}: below minimum')
        if a.maximum is not None and d>decimal(a.maximum):raise ValueError(f'{a.key}: above maximum')
        return d
    if a.type=='boolean':
        if type(v) is not bool:raise ValueError(f'{a.key}: expected boolean')
        return v
    if a.type=='category':
        if not isinstance(v,str) or v not in a.options:raise ValueError(f'{a.key}: choose one of {a.options}')
        return v
    if not isinstance(v,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',v):raise ValueError(f'{a.key}: expected YYYY-MM-DD')
    return date.fromisoformat(v)

class Expr(Strict):
    op:Literal['const','field','add','subtract','multiply','divide','min','max']='const'
    value:str | float | int | None=None
    field:str | None=None
    args:list[Expr]=Field(default_factory=list,max_length=10)
    @model_validator(mode='after')
    def valid(self):
        if self.op=='const':
            decimal(self.value)
            if self.field is not None or self.args:raise ValueError('Constant cannot have field or arguments')
        elif self.op=='field':
            if not self.field or self.value is not None or self.args:raise ValueError('Field expression requires only field')
        elif len(self.args)<2 or self.value is not None or self.field is not None:raise ValueError('Operator requires at least two arguments only')
        if self.op in ['subtract','divide'] and len(self.args)!=2:raise ValueError('Subtract and divide require two arguments')
        return self

class Condition(Strict):
    op:Literal['all','any','not','eq','ne','gt','gte','lt','lte','in','between']='all'
    field:str | None=None
    value:Any=None
    children:list[Condition]=Field(default_factory=list,max_length=20)
    @model_validator(mode='after')
    def valid(self):
        if self.op in ['all','any','not']:
            if self.field is not None or self.value is not None:raise ValueError('Logical group takes children only')
            if self.op=='not' and len(self.children)!=1:raise ValueError('NOT requires one condition')
            if self.op=='any' and not self.children:raise ValueError('OR requires conditions')
        elif self.field is None or self.children:raise ValueError('Comparison requires field, value and no children')
        return self

class Action(Strict):
    type:Literal['add','percent','multiply','set','basis_points']='percent'
    basis:Literal['base_amount','subtotal']='subtotal'
    value:Expr=Field(default_factory=lambda:Expr(value=0))

class Rule(Strict):
    id:str=Field(pattern=r'^[a-z][a-z0-9_]{0,69}$')
    name:str=Field(min_length=1,max_length=100)
    priority:int=100
    exclusive_group:str | None=None
    enabled:bool=True
    starts_at:datetime | None=None
    ends_at:datetime | None=None
    when:Condition=Field(default_factory=Condition)
    action:Action=Field(default_factory=Action)
    @model_validator(mode='after')
    def valid(self):
        for d in [self.starts_at,self.ends_at]:
            if d and d.tzinfo is None:raise ValueError('Effective dates need timezone')
        if self.starts_at and self.ends_at and self.starts_at>=self.ends_at:raise ValueError('Invalid rule interval')
        return self

class Bounds(Strict):
    minimum:Expr | None=None
    maximum:Expr | None=None
    round_to:str='1'
    @model_validator(mode='after')
    def valid(self):
        if decimal(self.round_to)<=0:raise ValueError('Rounding step must be positive')
        return self

class Scenario(Strict):
    name:str=Field(min_length=1,max_length=100)
    base_rate:str='100'
    context:dict[str,Any]
    expected_price:str | None=None
    expected_error:bool=False
    @model_validator(mode='after')
    def valid(self):
        if decimal(self.base_rate)<0:raise ValueError('Base rate must be nonnegative')
        if self.expected_price is not None:decimal(self.expected_price)
        if self.expected_error and self.expected_price is not None:raise ValueError('Expected error and price are mutually exclusive')
        return self

class Strategy(Strict):
    id:str=Field(pattern=r'^[a-z][a-z0-9_]{1,49}$')
    name:str=Field(min_length=2,max_length=80)
    description:str=Field(default='',max_length=500)
    output_type:Literal['money','rate']='money'
    currency:str=Field(default='INR',pattern=r'^[A-Z]{3}$')
    unit:str=Field(default='booking',min_length=1,max_length=60)
    attributes:list[Attribute]=Field(default_factory=list,max_length=30)
    base:Expr=Field(default_factory=lambda:Expr(op='field',field='base_rate'))
    rules:list[Rule]=Field(default_factory=list,max_length=60)
    constraints:Bounds=Field(default_factory=Bounds)
    scenarios:list[Scenario]=Field(default_factory=list,max_length=100)
    @model_validator(mode='after')
    def valid(self):
        keys=[a.key for a in self.attributes]
        if len(keys)!=len(set(keys)):raise ValueError('Duplicate attribute keys')
        attrs={a.key:a for a in self.attributes}
        numeric={a.key for a in self.attributes if a.type in ['number','integer']}|{'base_rate'}
        def expr(e,allowed,depth=0):
            if depth>8:raise ValueError('Expression nesting exceeds 8')
            if e.op=='field' and e.field not in allowed:raise ValueError(f'Unknown or non-numeric expression field: {e.field}')
            for child in e.args:expr(child,allowed,depth+1)
        def condition(c,depth=0):
            if depth>8:raise ValueError('Condition nesting exceeds 8')
            if c.op in ['all','any','not']:
                for child in c.children:condition(child,depth+1)
                return
            a=attrs.get(c.field)
            if a is None:raise ValueError(f'Unknown condition field: {c.field}')
            if a.type in ['category','boolean'] and c.op not in ['eq','ne','in']:raise ValueError('Category/boolean supports eq, ne, in only')
            values=c.value if c.op in ['in','between'] else [c.value]
            if not isinstance(values,list) or not values:raise ValueError('IN/BETWEEN requires a nonempty list')
            if c.op=='between' and len(values)!=2:raise ValueError('BETWEEN requires two values')
            # Type-check rule constants, but do not require thresholds to lie within input bounds.
            temp=a.model_copy(update={'minimum':None,'maximum':None})
            parsed=[check_value(temp,v) for v in values]
            if c.op=='between' and parsed[0]>parsed[1]:raise ValueError('Reversed BETWEEN range')
        expr(self.base,numeric)
        ids=set();groups=set()
        for r in self.rules:
            if r.id in ids:raise ValueError('Duplicate rule ID')
            ids.add(r.id);condition(r.when);expr(r.action.value,numeric|{'base_amount','subtotal'})
            if r.action.type=='basis_points' and self.output_type!='rate':raise ValueError('Basis points require rate output')
            if r.exclusive_group:
                pair=(r.exclusive_group,r.priority)
                if pair in groups:raise ValueError('Exclusive-group priorities must be unique')
                groups.add(pair)
        for e in [self.constraints.minimum,self.constraints.maximum]:
            if e:expr(e,numeric|{'base_amount'})
        return self

class ProductInput(Strict):
    id:str=Field(pattern=r'^[a-z][a-z0-9_]{1,49}$')
    name:str=Field(min_length=2,max_length=80)
    strategy_id:str
    base_rate:str='100'
    defaults:dict[str,Any]=Field(default_factory=dict)
    @model_validator(mode='after')
    def valid(self):
        if decimal(self.base_rate)<0:raise ValueError('Base rate cannot be negative')
        return self

class PriceRequest(Strict):
    product_id:str
    context:dict[str,Any]=Field(default_factory=dict)

class SimRequest(Strict):
    strategy_id:str
    version:int=Field(ge=1)
    scenarios:list[Scenario]=Field(min_length=1,max_length=100)
    at:datetime | None=None
    disabled_rule_ids:list[str]=Field(default_factory=list,max_length=60)
    @model_validator(mode='after')
    def valid(self):
        if self.at and self.at.tzinfo is None:raise ValueError('Simulation timestamp needs timezone')
        return self

class CompareRequest(SimRequest):
    baseline_version:int=Field(ge=1)

class VersionRequest(Strict):
    version:int=Field(ge=1)

class ValidationRequest(Strict):
    config:Strategy
    at:datetime | None=None
    @model_validator(mode='after')
    def valid(self):
        if self.at and self.at.tzinfo is None:raise ValueError('Timestamp needs timezone')
        return self

class CopilotRequest(Strict):
    instruction:str=Field(min_length=10,max_length=4000)
    config:Strategy
