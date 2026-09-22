"""Server-only model transport, bounded usage accounting, and safe status."""
import json
import os
import sqlite3
import time
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1]
ENV_KEYS = {"LLM_PROVIDER", "GROQ_API_KEY", "GROQ_MODEL", "OLLAMA_URL", "LLM_DAILY_REQUEST_LIMIT"}

def config():
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() in ENV_KEYS:
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
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
        row = db.execute("SELECT data FROM health WHERE provider=?", (provider,)).fetchone()
    return {"provider":provider, "model":os.getenv("GROQ_MODEL", "openai/gpt-oss-20b") if provider=="groq" else "local selection",
            "configured":provider=="ollama" or bool(os.getenv("GROQ_API_KEY")), "requests_today":count,
            "daily_request_limit":int(os.getenv("LLM_DAILY_REQUEST_LIMIT", "100")),
            "observation":json.loads(row[0]) if row else None}

def reserve(model):
    provider = config()
    if provider=="groq" and not os.getenv("GROQ_API_KEY"):
        raise ModelError("missing_key", "Groq is selected but GROQ_API_KEY is empty. Add it to the private .env file and restart the backend.")
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row=db.execute("SELECT data FROM health WHERE provider=?",(provider,)).fetchone()
        last=json.loads(row[0]) if row else {}
        if last.get("retry_at",0)>time.time():
            raise ModelError("rate_limit", f"The model is rate-limited. Retry in {max(1,int(last['retry_at']-time.time()))} seconds. Your conversation is saved.",429)
        n=db.execute("SELECT count(*) FROM calls WHERE provider=? AND at>=?",(provider,int(time.time()//86400)*86400)).fetchone()[0]
        if n>=int(os.getenv("LLM_DAILY_REQUEST_LIMIT","100")):
            raise ModelError("app_budget", "This application's daily model request limit has been reached. It resets at 00:00 UTC. Saved workflows can still replay without a model.",429)
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

async def chat(payload):
    url,headers,data=prepare(payload)
    provider,call_id=reserve(data['model'])
    try:
        async with httpx.AsyncClient(timeout=90,trust_env=False) as client:
            response=await client.post(url,headers=headers,json=data)
    except httpx.HTTPError as exc:
        return complete(provider,call_id,error=exc)
    return complete(provider,call_id,response)

def chat_sync(client,payload):
    url,headers,data=prepare(payload)
    provider,call_id=reserve(data['model'])
    try: response=client.post(url,headers=headers,json=data)
    except httpx.HTTPError as exc: return complete(provider,call_id,error=exc)
    return complete(provider,call_id,response)
