"""Boundary tests use explicit model doubles, not runtime model evidence."""
import asyncio
import json
import httpx
import pytest
from fastapi.testclient import TestClient
from engine.api import create_app
from engine.catalog_agent import match_capabilities
from tests.test_browser import fixture_capability


def test_opposite_effect_is_rejected():
    from engine.catalog_agent import conflicting_effect
    cap = fixture_capability()
    cap.success.name = 'Card frozen'
    assert conflicting_effect('Unfreeze a card', cap)
    assert not conflicting_effect('Freeze a misplaced card', cap)


def test_empty_catalog_needs_no_model_and_never_starts_run(tmp_path, monkeypatch):
    monkeypatch.setenv('DASHBOARD_STORAGE', str(tmp_path))
    (tmp_path/'.hide-example').touch()
    with TestClient(create_app()) as client:
        client.headers['Origin'] = 'http://127.0.0.1:5174'
        reply = client.post('/api/session', json={'profile_id': 'mira'})
        client.headers['X-CSRF-Token'] = reply.json()['csrf']
        assert client.post('/api/agent/match', json={'message': 'freeze a debit card'}).json() == {'matches': [], 'model_used': False, 'catalog_count': 0}
        assert client.get('/api/runs').json() == []
        assert client.post('/api/agent/match', json={'message': ' '}).status_code == 422


@pytest.mark.parametrize('ids,valid', [(['saved'], True), ([], True), (['invented'], False)])
def test_model_selection_must_reference_catalog(monkeypatch, ids, valid):
    async def response(self, url, **kwargs):
        sent = kwargs['json']
        assert 'steps' not in json.loads(sent['messages'][1]['content'])['catalog'][0]
        return httpx.Response(200, request=httpx.Request('POST', 'http://local/api/chat'), json={'message': {'content': json.dumps({'choice': ids[0] if ids else 'NO_MATCH'})}})
    monkeypatch.setattr(httpx.AsyncClient, 'post', response)
    call = match_capabilities('change a mailing address', {'saved': fixture_capability()}, 'mistral:latest')
    if valid:
        assert asyncio.run(call)['matches'] == ids
    else:
        with pytest.raises(ValueError): asyncio.run(call)
