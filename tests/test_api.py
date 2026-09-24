"""API boundaries without mocked discovery or fake success evidence."""
from fastapi.testclient import TestClient
from engine.api import create_app
import pytest


@pytest.mark.parametrize('path,payload,function,result', [
    ('/api/agent/match', {'message':'Update an address'}, 'match_capabilities', {'matches':['example'],'model_used':True}),
    ('/api/agent/inputs', {'message':'C-205','capability_id':'example'}, 'extract_inputs', {'customer_id':'C-205'}),
    ('/api/agent/discovery', {'message':'Update an address'}, 'match_capabilities', {'matches':[],'model_used':True}),
    ('/api/agent/setup', {'message':'Learn it','stage':'method'}, 'interpret_setup_reply', 'learn'),
])
def test_optional_conversation_header_preserves_trace_link_without_task_changes(tmp_path, monkeypatch, trace_capture, path, payload, function, result):
    import uuid
    from engine import telemetry
    import engine.catalog_agent as agent
    calls=[]
    @telemetry.traced('test.chat')
    async def model_double(*args):
        calls.append(args)
        return result
    monkeypatch.setattr(agent,function,model_double)
    monkeypatch.setenv('DASHBOARD_STORAGE',str(tmp_path))
    identifier=str(uuid.uuid4())
    with TestClient(create_app()) as client:
        client.headers['Origin']='http://127.0.0.1:5174'
        session=client.post('/api/session',json={'profile_id':'mira'})
        client.headers['X-CSRF-Token']=session.json()['csrf']
        for headers,body in [({'X-Conversation-ID':identifier},payload), ({},{**payload,'conversation_id':identifier})]:
            assert client.post(path,headers=headers,json=body).status_code==200
            assert trace_capture[-1].record['extra']['metadata']['conversation_id']==identifier
        assert len(calls)==2
        assert client.post(path,headers={'X-Conversation-ID':'not-a-uuid'},json=payload).status_code==422
        assert client.post(path,headers={'X-Conversation-ID':identifier},json={**payload,'conversation_id':str(uuid.uuid4())}).status_code==422
        assert client.post(path,headers={'X-Conversation-ID':identifier},json={**payload,'unexpected_business_field':True}).status_code==422
        assert len(calls)==2  # Invalid requests never reached a model handler.
        assert client.get('/api/runs').json()==[]


def test_reset_workspace_hides_example_across_restarts(tmp_path, monkeypatch):
    monkeypatch.setenv("DASHBOARD_STORAGE", str(tmp_path))
    (tmp_path / ".hide-example").touch()
    for _ in range(2):
        with TestClient(create_app()) as client:
            client.headers["Origin"] = "http://127.0.0.1:5174"
            response = client.post("/api/session", json={"profile_id": "mira"})
            client.headers["X-CSRF-Token"] = response.json()["csrf"]
            assert client.get("/api/capabilities").json() == []
            assert client.get("/api/runs").json() == []
            assert client.post("/api/runs", json={"mode": "replay", "capability_id": "example", "inputs": {}}).status_code == 400


def test_api_session_origin_and_role_controls(tmp_path, monkeypatch):
    monkeypatch.setenv("DASHBOARD_STORAGE", str(tmp_path))
    with TestClient(create_app()) as client:
        assert client.get('/api/runs').status_code == 401
        assert client.post('/api/session', json={'profile_id':'mira'}).status_code == 403
        client.headers['Origin']='http://127.0.0.1:5174'
        response=client.post('/api/session',json={'profile_id':'taylor'})
        assert response.status_code==200
        client.headers['X-CSRF-Token']=response.json()['csrf']
        assert client.get('/api/capabilities').status_code==200
        invocation={'mode':'replay','inputs':{'customer_id':'C-104','street':'Example','city':'Demo','postal':'12345'}}
        assert client.post('/api/runs',json=invocation).status_code==403
        response=client.post('/api/session',json={'profile_id':'mira'})
        assert client.post('/api/runs',json=invocation).status_code==403
        client.headers['X-CSRF-Token']=response.json()['csrf']
        invalid={**invocation,'capability_id':'../../.env'}
        assert client.post('/api/runs',json=invalid).status_code==400
        assert client.post('/api/runs',json={**invocation,'inputs':{}}).status_code==422
        assert client.post('/api/runs',json={**invocation,'entry':'https://example.com'}).status_code==422
        client.headers['Origin']='https://attacker.example'
        assert client.post('/api/runs',json=invocation).status_code==403


def test_restart_marks_unfinished_jobs_as_failed(tmp_path,monkeypatch):
    import json
    monkeypatch.setenv('DASHBOARD_STORAGE',str(tmp_path))
    (tmp_path/'job-example.json').write_text(json.dumps({'id':'example','status':'running','created':1,'mode':'replay'}))
    with TestClient(create_app()) as client:
        client.headers['Origin']='http://127.0.0.1:5174'
        client.post('/api/session',json={'profile_id':'mira'})
        runs=client.get('/api/runs').json()
        assert runs[0]['status']=='failure'
        assert 'restarted' in runs[0]['code']


def test_human_draft_requires_operator_review_to_enter_catalog(tmp_path, monkeypatch):
    import json
    from tests.test_browser import fixture_capability
    monkeypatch.setenv('DASHBOARD_STORAGE',str(tmp_path))
    (tmp_path/'drafts').mkdir()
    cap=fixture_capability().model_copy(update={'source':'human'})
    (tmp_path/'drafts'/'recording-test.json').write_text(cap.model_dump_json())
    (tmp_path/'job-recording-test.json').write_text(json.dumps({'id':'recording-test','mode':'recording','status':'success','created':1,'capability_id':'example'}))
    with TestClient(create_app()) as client:
        client.headers['Origin']='http://127.0.0.1:5174'
        response=client.post('/api/session',json={'profile_id':'taylor'})
        client.headers['X-CSRF-Token']=response.json()['csrf']
        assert 'recording-test' not in [c['id'] for c in client.get('/api/capabilities').json()]
        assert client.post('/api/runs/recording-test/publish').status_code==403
        response=client.post('/api/session',json={'profile_id':'mira'})
        client.headers['X-CSRF-Token']=response.json()['csrf']
        assert client.post('/api/runs/recording-test/publish').status_code==200
        assert client.post('/api/runs/recording-test/publish').status_code==200
        item=next(c for c in client.get('/api/capabilities').json() if c['id']=='recording-test')
        assert item['capability']['source']=='human'
        assert client.get('/api/runs/recording-test/captures/.env').status_code==404
        assert client.get('/api/workflow-spec').json()['inputs']['postal']['pattern']=='[0-9]{5}'


def test_automation_rejects_clicks_and_accepts_control_request(tmp_path, monkeypatch):
    import threading
    from engine.contracts import Result
    import engine.api as api
    gate=threading.Event()
    started=threading.Event()
    def waiting_executor(*args, **kwargs):
        started.set()
        gate.wait(5)
        return Result(status='failure',code='Scripted test stopped',run_id='test')
    monkeypatch.setattr(api,'replay',waiting_executor)
    monkeypatch.setenv('DASHBOARD_STORAGE',str(tmp_path))
    with TestClient(create_app()) as client:
        client.headers['Origin']='http://127.0.0.1:5174'
        response=client.post('/api/session',json={'profile_id':'mira'})
        client.headers['X-CSRF-Token']=response.json()['csrf']
        try:
            response=client.post('/api/runs',json={'mode':'replay','inputs':{'customer_id':'C-104','street':'Example','city':'Demo','postal':'12345'}})
            assert response.status_code==202
            assert started.wait(2)
            path='/api/runs/'+response.json()['id']+'/control'
            assert client.post(path,json={'kind':'click','x':20,'y':20}).status_code==409
            assert client.post(path,json={'kind':'type','text':'cannot type'}).status_code==409
            assert client.post(path,json={'kind':'request_control'}).status_code==200
            assert client.get('/api/runs').json()[0]['live']['takeover_requested'] is True
        finally:
            gate.set()
