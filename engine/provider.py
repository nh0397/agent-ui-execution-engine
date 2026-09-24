"""Server-only model transport, bounded usage accounting, and safe status."""
import json
import os
import re
import math
import sqlite3
import time
from pathlib import Path
import httpx
from engine.settings import load_env
from engine.telemetry import traced, model_sent

ROOT = Path(__file__).resolve().parents[1]
ENV_KEYS = {"LLM_PROVIDER", "GROQ_API_KEY", "GROQ_MODEL", "OLLAMA_URL", "LLM_DAILY_REQUEST_LIMIT", "LLM_REQUESTS_PER_MINUTE"}

def config():
    load_env(ENV_KEYS)
    provider = os.getenv("LLM_PROVIDER", "ollama").lower()
    if provider not in {"ollama", "groq"}:
        raise ModelError("configuration", "LLM_PROVIDER must be ollama or groq.", 503)
    return provider

class ModelError(ValueError):
    def __init__(self, code, message, status=503):
        super().__init__(message)
        self.code, self.status = code, status

def connect():
    root = Path(os.getenv("DASHBOARD_STORAGE", str(ROOT / "work/dashboard")))
    root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(root / "model-usage.sqlite3", timeout=10)
    db.execute("CREATE TABLE IF NOT EXISTS calls (at REAL, provider TEXT, model TEXT, status TEXT, input_tokens INTEGER, output_tokens INTEGER)")
    db.execute("CREATE TABLE IF NOT EXISTS health (provider TEXT PRIMARY KEY, data TEXT)")
    return db

def status():
    provider = config()
    with connect() as db:
        count = db.execute("SELECT count(*) FROM calls WHERE provider=? AND at>=?", (provider, int(time.time() // 86400)*86400)).fetchone()[0]
        tokens = db.execute("SELECT COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0) FROM calls WHERE provider=? AND at>=?", (provider, int(time.time() // 86400)*86400)).fetchone()
        row = db.execute("SELECT data FROM health WHERE provider=?", (provider,)).fetchone()
    return {"provider":provider, "model":os.getenv("GROQ_MODEL", "openai/gpt-oss-20b") if provider=="groq" else "local selection",
            "configured":provider=="ollama" or bool(os.getenv("GROQ_API_KEY")), "requests_today":count,
            "daily_request_limit":int(os.getenv("LLM_DAILY_REQUEST_LIMIT", "100")),
            "requests_per_minute":int(os.getenv("LLM_REQUESTS_PER_MINUTE", "10")),
            "input_tokens_today":tokens[0], "output_tokens_today":tokens[1],
            "observation":json.loads(row[0]) if row else None}

def reset_seconds(value):
    """Parse documented duration headers; unknown formats give no prediction."""
    if not re.fullmatch(r'(?:[0-9]+(?:\.[0-9]+)?(?:ms|s|m|h))+', value or ''):
        return 0
    units={'ms':.001,'s':1,'m':60,'h':3600}
    return sum(float(n)*units[u] for n,u in re.findall(r'([0-9]+(?:\.[0-9]+)?)(ms|s|m|h)',value))


def reserve(model, estimated_tokens=0):
    provider = config()
    if provider=="groq" and not os.getenv("GROQ_API_KEY"):
        raise ModelError("missing_key", "Groq is selected but GROQ_API_KEY is empty. Add it to the private .env file and restart the backend.")
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row=db.execute("SELECT data FROM health WHERE provider=?",(provider,)).fetchone()
        last=json.loads(row[0]) if row else {}
        if last.get("retry_at",0)>time.time():
            raise ModelError("rate_limit", f"The model is rate-limited. Retry in {max(1,int(last['retry_at']-time.time()))} seconds. Your conversation is saved.",429)
        limits=last.get('limits',{})
        if provider=='groq' and estimated_tokens:
            try: remaining=int(limits.get('x-ratelimit-remaining-tokens','-1'))
            except ValueError: remaining=-1
            reset_at=last.get('checked_at',0)+reset_seconds(limits.get('x-ratelimit-reset-tokens',''))
            if 0 <= remaining < estimated_tokens and reset_at>time.time():
                raise ModelError('token_headroom', 'Waiting for provider-reported token capacity before sending another request.',429)
        n=db.execute("SELECT count(*) FROM calls WHERE provider=? AND at>=?",(provider,int(time.time()//86400)*86400)).fetchone()[0]
        if n>=int(os.getenv("LLM_DAILY_REQUEST_LIMIT","100")):
            raise ModelError("app_budget", "This application's daily model request limit has been reached. It resets at 00:00 UTC. Saved workflows can still replay without a model.",429)
        recent=db.execute("SELECT count(*),min(at) FROM calls WHERE provider=? AND at>?",(provider,time.time()-60)).fetchone()
        if recent[0]>=int(os.getenv("LLM_REQUESTS_PER_MINUTE","10")):
            raise ModelError("app_rate", f"Application pacing limit reached. Retry in {max(1,int(recent[1]+60-time.time())+1)} seconds. No provider call was made.",429)
        cursor=db.execute("INSERT INTO calls VALUES(?,?,?,'pending',NULL,NULL)",(time.time(),provider,model))
        return provider,cursor.lastrowid

def prepare(payload):
    provider=config()
    if provider=="ollama":
        return os.getenv("OLLAMA_URL","http://127.0.0.1:11434").rstrip('/')+'/api/chat',{},payload
    # JSON mode plus independently validated application schemas. No paid failover.
    return "https://api.groq.com/openai/v1/chat/completions", {"Authorization":"Bearer "+os.getenv("GROQ_API_KEY","")}, {
        "model":os.getenv("GROQ_MODEL","openai/gpt-oss-20b"), "stream":False,
        "temperature":0,"max_completion_tokens":2048,"response_format":{"type":"json_object"},
        "messages":[{"role":"system","content":"Return only a JSON object matching this schema: "+json.dumps(payload['format'])},*payload['messages']]}

def complete(provider, call_id, response=None, error=None):
    state={"checked_at":time.time(),"state":"unavailable" if error else "ready"}
    body={}
    if response is not None:
        state['state']='ready' if response.is_success else 'error'
        if provider=='groq':
            state['limits']={key:response.headers[key][:80] for key in (
                'x-ratelimit-remaining-requests','x-ratelimit-remaining-tokens','x-ratelimit-reset-requests','x-ratelimit-reset-tokens') if key in response.headers}
        if response.status_code==429:
            state['state']='rate_limited'
            try: delay=max(1,min(86400,float(response.headers.get('retry-after','60'))))
            except ValueError: delay=60
            state['retry_at']=time.time()+delay
        if response.is_success:
            try: body=response.json()
            except ValueError: state['state']='invalid_response'
    usage=body.get('usage',{})
    with connect() as db:
        db.execute("UPDATE calls SET status=?,input_tokens=?,output_tokens=? WHERE rowid=?",(state['state'],usage.get('prompt_tokens',body.get('prompt_eval_count')),usage.get('completion_tokens',body.get('eval_count')),call_id))
        db.execute("INSERT OR REPLACE INTO health VALUES(?,?)",(provider,json.dumps(state)))
    if error:
        if provider=="groq" and isinstance(error, httpx.TimeoutException):
            raise ModelError("timeout", "Groq timed out. Retry when ready; no automatic retry was made.", 504) from None
        if provider=="groq": raise ModelError("connection", "Groq did not respond successfully. Check your connection and retry; no automatic retry was made.") from None
        raise error
    if response.status_code==429:
        raise ModelError('rate_limit','The provider rate limit or quota has been reached. Your conversation is saved. Check Model status for retry timing; no automatic retry or provider switch will occur.',429)
    if provider=='groq' and response.status_code in (401,403):
        raise ModelError('credentials','Groq rejected the API key or model permission. Check the private backend configuration.')
    if provider=="groq" and response.status_code>=400:
        raise ModelError("provider_error", "Groq rejected the request or is unavailable. Check the configured model and provider status; no automatic retry was made.")
    response.raise_for_status()
    if provider=='groq':
        return {'message':{'content':body['choices'][0]['message']['content']},'prompt_eval_count':usage.get('prompt_tokens'),'eval_count':usage.get('completion_tokens')}
    return body

@traced("model.request", "llm")
async def chat(payload):
    url,headers,data=prepare(payload)
    provider,call_id=reserve(data['model'], math.ceil(len(json.dumps(data.get('messages',[])).encode('utf-8'))/4)+data.get('max_completion_tokens',0))
    try:
        async with httpx.AsyncClient(timeout=90,trust_env=False) as client:
            model_sent(provider, data['model'])
            response=await client.post(url,headers=headers,json=data)
    except httpx.HTTPError as exc:
        return complete(provider,call_id,error=exc)
    return complete(provider,call_id,response)

@traced("model.request", "llm")
def chat_sync(client,payload, wait_for_capacity=None):
    url,headers,data=prepare(payload)
    while True:
        try:
            provider,call_id=reserve(data['model'], math.ceil(len(json.dumps(data.get('messages',[])).encode('utf-8'))/4)+data.get('max_completion_tokens',0))
            break
        except ModelError as exc:
            # No request has been sent. Local pacing or observed token headroom may wait.
            # Provider 429s, daily budgets and credentials still fail immediately.
            if exc.code not in {'app_rate', 'token_headroom'} or wait_for_capacity is None:
                raise
            wait_for_capacity()
            time.sleep(.1)
    model_sent(provider, data['model'])
    try: response=client.post(url,headers=headers,json=data)
    except httpx.HTTPError as exc: return complete(provider,call_id,error=exc)
    return complete(provider,call_id,response)
