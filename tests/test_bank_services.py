"""Real-browser service recording/replay; gestures are scripted test inputs."""
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from demo.app import create_app
from demo.database import connect
from engine.api import LiveControl
from engine.contracts import Capability, Profile
from engine.runtime import replay
from engine.surface import BrowserSurface
from tests.test_browser import server


@pytest.mark.parametrize("service,key,example,new_value,heading,outputs", [
    ("balance", "account_id", "AC-4104", "AC-4205", "Account balance verified", {"Verified account ID": "account_id", "Account balance": "balance"}),
    ("freeze", "card_id", "DC-104", "DC-205", "Card frozen", {"Saved card ID": "card_id", "Saved card status": "status", "Card confirmation reference": "reference"}),
])
def test_record_service_and_replay_different_record(tmp_path, server, monkeypatch, service, key, example, new_value, heading, outputs):
    import engine.recording as recording
    import httpx
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(Path(".browsers").resolve()))
    origin = server("normal")
    profile = Profile.model_validate_json(Path("config/customer-service.json").read_text())
    profile.origins = [origin]
    control = LiveControl()
    gestures = ([('link', 'Accounts'), ('focus', 'Account ID'), ('fill', key, example), ('button', 'Search accounts'), ('link', 'Open account')]
                if service == 'balance' else [('link', 'Debit cards'), ('focus', 'Card ID'), ('fill', key, example), ('button', 'Search cards'), ('button', 'Review freeze'), ('button', 'Freeze card')])
    class ScriptedSurface(BrowserSurface):
        def pump_events(self):
            super().pump_events()
            if control.recording.get('error'):
                raise AssertionError(control.recording['error'])
            if gestures:
                item = gestures.pop(0)
                if item[0] == 'fill':
                    command = {'kind': 'type', 'parameter_key': item[1], 'text': item[2]}
                else:
                    target = self.page.get_by_label(item[1], exact=True) if item[0] == 'focus' else self.page.get_by_role(item[0], name=item[1], exact=True)
                    target.scroll_into_view_if_needed()
                    box = target.bounding_box()
                    command = {'kind': 'click', 'x': box['x'] + box['width']/2, 'y': box['y'] + box['height']/2}
            else:
                command = {'kind': 'finish', 'success_name': heading, 'output_bindings': outputs}
            control.commands.put({**command, 'operator_id': 'scripted-test'})
    monkeypatch.setattr(recording, 'BrowserSurface', ScriptedSurface)
    draft = tmp_path / f'{service}.json'
    result = recording.record(service, f'{service} service', profile, origin, tmp_path/'recorded', draft, control)
    assert result.status == 'success', (result, control.recording)
    cap = Capability.model_validate_json(draft.read_text())
    assert set(cap.inputs) == {key}
    monkeypatch.setattr(httpx.Client, 'send', lambda *a, **kw: (_ for _ in ()).throw(AssertionError('Replay must not call a model')))
    result = replay(cap, {key: new_value}, profile, origin, tmp_path/'replayed', approve_writes=True)
    assert result.status == 'success', result
    assert result.outputs[key] == new_value
    assert result.outputs.get('balance', '4200.75') == '4200.75'
    assert result.outputs.get('status', 'Frozen') == 'Frozen'
    missing = replay(cap, {key: 'AC-999' if service == 'balance' else 'DC-999'}, profile, origin, tmp_path/'missing', approve_writes=True)
    assert missing.status == 'business_outcome'


def test_card_csrf_idempotency_conflict_and_restore(tmp_path):
    import re
    database = tmp_path/'bank.db'
    app = create_app(database)
    with TestClient(app) as client, TestClient(app) as other:
        def token(c):
            page = c.get('/cards/search?card_id=DC-104').text
            return re.search(r'name="csrf" value="([^"]+)"', page)[1]
        csrf, second = token(client), token(other)
        assert 'Permission denied' in client.post('/cards/review', data={'card_id': 'DC-104', 'status': 'Frozen'}).text
        for c, t in [(client, csrf), (other, second)]:
            assert 'Review card status change' in c.post('/cards/review', data={'csrf': t, 'card_id': 'DC-104', 'status': 'Frozen'}).text
        first = client.post('/cards/save', data={'csrf': csrf})
        assert 'Card frozen' in first.text
        repeated = client.post('/cards/save', data={'csrf': csrf})
        assert repeated.url == first.url
        assert 'Record changed during review' in other.post('/cards/save', data={'csrf': second}).text
        client.post('/cards/review', data={'csrf': csrf, 'card_id': 'DC-104', 'status': 'Active'})
        assert 'Card unfrozen' in client.post('/cards/save', data={'csrf': csrf}).text
        with connect(database) as conn:
            assert conn.execute('SELECT status FROM cards WHERE id=?', ('DC-104',)).fetchone()['status'] == 'Active'
            assert conn.execute('SELECT COUNT(*) AS n FROM card_events').fetchone()['n'] == 2


def test_bulk_seed_preserves_edits_and_paginates(tmp_path):
    database = tmp_path/'seed.db'
    create_app(database)
    with connect(database) as conn:
        conn.execute("UPDATE customers SET city=? WHERE id=?", ('Edited City', 'C-1000'))
    app = create_app(database)
    with connect(database) as conn:
        counts = {table: conn.execute('SELECT COUNT(*) AS n FROM '+table).fetchone()['n'] for table in ('customers', 'accounts', 'cards', 'transactions')}
        assert counts == {'customers': 1003, 'accounts': 1004, 'cards': 1003, 'transactions': 4004}
        assert conn.execute('SELECT city FROM customers WHERE id=?', ('C-1000',)).fetchone()['city'] == 'Edited City'
        assert conn.execute('SELECT COUNT(*) AS n FROM cards LEFT JOIN customers ON cards.customer=customers.id WHERE customers.id IS NULL').fetchone()['n'] == 0
    with TestClient(app) as client:
        first, second = client.get('/').text, client.get('/?page_number=2').text
        assert first.count('<tr>') == 21 and second.count('<tr>') == 21
        assert 'Next page' in first and 'Previous page' in second
        assert 'Demo Member 1000' in client.get('/customers?customer_id=C-1999').text
