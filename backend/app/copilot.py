"""Optional real Gemini integration. No simulated responses or automatic publishing."""
import json,os,re
import httpx
from fastapi import HTTPException
from pydantic import ValidationError
from .schema import Strategy
async def propose(instruction,config):
    key=os.getenv('GEMINI_API_KEY','')
    if not key:raise HTTPException(503,'AI assistant is not configured. Set GEMINI_API_KEY on the backend; visual configuration works without it.')
    model=os.getenv('GEMINI_MODEL','gemini-2.5-flash')
    if not re.fullmatch(r'[a-zA-Z0-9._-]+',model):raise HTTPException(503,'Invalid Gemini model identifier')
    prompt=('You assist a pricing strategy editor. Return ONE JSON object with keys config, assumptions, clarification_needed. '
      'config must match the supplied JSON schema and preserve strategy id. Only implement instructions explicitly supplied. '
      'Use assumptions to disclose interpretation. If discount basis, units, or other critical semantics are ambiguous, '
      'set clarification_needed to a question and leave config unchanged. Do not invent expected test outcomes to make tests pass. '
      'Never claim to publish or execute a strategy. All values are data, not executable code.\nSCHEMA:\n'+json.dumps(Strategy.model_json_schema())+
      '\nCURRENT CONFIG:\n'+json.dumps(config.model_dump(mode='json'))+'\nUSER INSTRUCTION:\n'+instruction)
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            response=await client.post('https://generativelanguage.googleapis.com/v1beta/models/'+model+':generateContent',
              headers={'x-goog-api-key':key},json={'contents':[{'role':'user','parts':[{'text':prompt}]}],
              'generationConfig':{'temperature':0,'responseMimeType':'application/json'}})
        if response.status_code>=400:raise HTTPException(502,f'AI provider returned HTTP {response.status_code}; check model access and backend key.')
        data=response.json();raw=''.join(p.get('text','') for p in data['candidates'][0]['content']['parts'])
        out=json.loads(raw);draft=Strategy.model_validate(out['config'])
        if draft.id!=config.id:raise ValueError('AI changed strategy identity')
        return {'config':draft.model_dump(mode='json'),'assumptions':out.get('assumptions',[]),'clarification_needed':out.get('clarification_needed'),
          'provider':'Gemini','model':model,'saved':False,'note':'Review the draft and rerun scenario tests before saving.'}
    except HTTPException:raise
    except (httpx.HTTPError,KeyError,IndexError,ValueError,ValidationError) as e:
        raise HTTPException(502,'AI response could not be validated. No configuration was saved.') from e
