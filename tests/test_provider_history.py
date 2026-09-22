import asyncio
import json
import uuid
import httpx
import pytest
from fastapi.testclient import TestClient
from engine import provider
from engine.api import create_app

@pytest.fixture
def isolated(tmp_path,monkeypatch):
    monkeypatch.setenv('DASHBOARD_STORAGE',str(tmp_path))
    monkeypatch.setenv('LLM_PROVIDER','groq')
    monkeypatch.setenv('GROQ_API_KEY','gsk_'+'x'*30)
    monkeypatch.setenv('LLM_DAILY_REQUEST_LIMIT','3')
    return tmp_path

PAYLOAD={'model':'mistral:latest','format':{'type':'object'},'messages':[{'role':'user','content':'private prompt'}]}

def test_key_never_in_body_or_status_and_usage_persists(isolated,monkeypatch):
    async def post(self,url,**kwargs):
        assert url=='https://api.groq.com/openai/v1/chat/completions'
        assert kwargs['headers']['Authorization'].startswith('Bearer gsk_')
        assert 'gsk_' not in json.dumps(kwargs['json'])
        return httpx.Response(200,request=httpx.Request('POST',url),headers={'x-ratelimit-remaining-requests':'9'},json={'choices':[{'message':{'content':'{"choice":"NO_MATCH"}'}}],'usage':{'prompt_tokens':10,'completion_tokens':3}})
    monkeypatch.setattr(httpx.AsyncClient,'post',post)
    assert asyncio.run(provider.chat(PAYLOAD))['prompt_eval_count']==10
    status=provider.status()
    assert status['requests_today']==1
    assert status['observation']['limits']['x-ratelimit-remaining-requests']=='9'
    assert 'gsk_' not in json.dumps(status)
    with provider.connect() as db:
        assert db.execute('select input_tokens,output_tokens from calls').fetchone()==(10,3)
    assert b'private prompt' not in (isolated/'model-usage.sqlite3').read_bytes()

def test_quota_stops_retry_without_another_provider_call(isolated,monkeypatch):
    calls=[]
    async def post(self,url,**kwargs):
        calls.append(url)
        return httpx.Response(429,request=httpx.Request('POST',url),headers={'retry-after':'120'},text='private provider body')
    monkeypatch.setattr(httpx.AsyncClient,'post',post)
    for _ in range(2):
        with pytest.raises(provider.ModelError) as error: asyncio.run(provider.chat(PAYLOAD))
        assert error.value.status==429
        assert 'private' not in str(error.value)
    assert len(calls)==1

def test_missing_key_and_application_budget(isolated,monkeypatch):
    monkeypatch.setenv('GROQ_API_KEY','')
    with pytest.raises(provider.ModelError,match='empty'):provider.reserve('test')
    monkeypatch.setenv('GROQ_API_KEY','test-key')
    for _ in range(3):provider.reserve('test')
    with pytest.raises(provider.ModelError,match='daily'):provider.reserve('test')

def login(client,name='mira'):
    client.headers['Origin']='http://127.0.0.1:5174'
    client.headers['X-CSRF-Token']=client.post('/api/session',json={'profile_id':name}).json()['csrf']

def test_conversation_restart_profile_isolation_conflict_and_no_execution(isolated):
    id=str(uuid.uuid4());body={'messages':[{'role':'you','text':'gsk_'+'x'*30+' Check account AC-10002'}]}
    with TestClient(create_app()) as client:
        login(client)
        assert client.put('/api/conversations/'+id,json=body).status_code==200
        assert client.put('/api/conversations/'+id,json=body).status_code==409
        assert 'gsk_' not in client.get('/api/conversations/'+id).text
        login(client,'sam')
        assert client.get('/api/conversations').json()==[]
        assert client.get('/api/conversations/'+id).status_code==404
        assert client.put('/api/conversations/'+id,json=body).status_code==404
    with TestClient(create_app()) as client:
        login(client)
        assert client.get('/api/conversations/'+id).json()['messages'][0]['text'].startswith('[REDACTED]')
        assert len(client.get('/api/conversations').json())==1
        assert client.get('/api/runs').json()==[]

def test_provider_timeout_is_safe_and_distinct(isolated, monkeypatch):
    async def post(self,url,**kwargs):
        raise httpx.ReadTimeout('private key or response details')
    monkeypatch.setattr(httpx.AsyncClient,'post',post)
    with pytest.raises(provider.ModelError) as error:
        asyncio.run(provider.chat(PAYLOAD))
    assert error.value.status==504
    assert error.value.code=='timeout'
    assert 'private' not in str(error.value)


def test_setup_preserves_key_and_fills_blank_database_password(tmp_path, monkeypatch):
    from demo.setup import main
    monkeypatch.chdir(tmp_path)
    path=tmp_path/'.env'
    path.write_text('LLM_PROVIDER=groq\nGROQ_API_KEY=existing-private-key\nDEMO_DB_PASSWORD=\n',encoding='utf-8')
    main()
    first=path.read_text(encoding='utf-8')
    main()
    assert path.read_text(encoding='utf-8')==first
    assert 'GROQ_API_KEY=existing-private-key' in first
    assert 'LLM_PROVIDER=groq' in first
    assert len(next(line.split('=',1)[1] for line in first.splitlines() if line.startswith('DEMO_DB_PASSWORD=')))==48
