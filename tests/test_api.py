"""API boundaries without mocked discovery or fake success evidence."""
from fastapi.testclient import TestClient
from engine.api import create_app


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
