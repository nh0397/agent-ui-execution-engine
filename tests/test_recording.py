"""Scripted demonstrations validate recording; they are not human participation evidence."""
import json
import os
from pathlib import Path

from engine.api import LiveControl
from engine.contracts import Capability, Profile
from engine.runtime import replay
from engine.surface import BrowserSurface
from tests.test_browser import server


def test_record_publishable_contract_and_replay_new_inputs(tmp_path, server, monkeypatch):
    import engine.recording as recording
    os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH',str(Path('.browsers').resolve()))
    origin=server('normal')
    profile=Profile.model_validate_json(Path('config/customer-service.json').read_text());profile.origins=[origin]
    control=LiveControl()
    gestures=[('focus','Customer ID'),('fill','customer_id','C-104'),('button','Search customers'),
        ('link','Open customer'),('link','Edit mailing address'),('focus','Street address'),
        ('fill','street','77 Private Canary Street'),('focus','City'),('fill','city','Canaryville'),
        ('focus','Postal code'),('fill','postal','87654'),('button','Review changes'),('button','Save address')]
    class ScriptedSurface(BrowserSurface):
        def pump_events(self):
            super().pump_events()
            if gestures:
                item=gestures.pop(0)
                if item[0]=='fill':
                    command={'kind':'type','parameter_key':item[1],'text':item[2]}
                else:
                    locator=self.page.get_by_label(item[1],exact=True) if item[0]=='focus' else self.page.get_by_role(item[0],name=item[1],exact=True)
                    box=locator.bounding_box()
                    command={'kind':'click','x':box['x']+box['width']/2,'y':box['y']+box['height']/2}
            else:
                command={'kind':'finish','success_name':'Address updated','output_bindings':{
                    'Saved customer ID':'customer_id','Saved street address':'street','Saved city':'city','Saved postal code':'postal','Confirmation reference':'confirmation_reference'}}
            command['operator_id']='scripted-test'
            control.commands.put(command)
    monkeypatch.setattr(recording,'BrowserSurface',ScriptedSurface)
    draft=tmp_path/'draft.json'
    result=recording.record('address_from_human','Update a customer address',profile,origin,tmp_path/'recorded',draft,control)
    assert result.status=='success', (result,control.recording)
    cap=Capability.model_validate_json(draft.read_text())
    assert cap.source=='human' and len(cap.steps)==14
    assert set(cap.inputs)=={'customer_id','street','city','postal'}
    folder=tmp_path/'recorded'/result.run_id
    assert len(list(folder.glob('step-*.png')))==26
    assert (folder/'WORKFLOW.md').exists()
    text=''.join(p.read_text() for p in folder.iterdir() if p.suffix in ('.json','.jsonl','.md'))
    assert '77 Private Canary Street' not in text and 'Canaryville' not in text
    assert all(p.read_bytes().startswith(b'\x89PNG') for p in folder.glob('*.png'))
    import httpx
    monkeypatch.setattr(httpx.Client,'send',lambda *a,**k: (_ for _ in ()).throw(AssertionError('No model transport during replay')))
    output=replay(cap,json.loads(Path('config/inputs-b.json').read_text()),profile,origin,tmp_path/'replayed',approve_writes=True)
    assert output.status=='success', output
    assert output.outputs['customer_id']=='C-205'


def test_user_request_transfers_control_before_next_action(tmp_path, server):
    from tests.test_browser import fixture_capability
    os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH',str(Path('.browsers').resolve()))
    origin=server('normal')
    profile=Profile.model_validate_json(Path('config/customer-service.json').read_text());profile.origins=[origin]
    control=LiveControl();control.takeover.set();control.commands.put({'kind':'resume','operator_id':'scripted-test'})
    output=replay(fixture_capability(),json.loads(Path('config/inputs-b.json').read_text()),profile,origin,tmp_path/'runs',approve_writes=True,control=control)
    assert output.status=='success' and output.human_assisted
    events=[json.loads(line) for line in next((tmp_path/'runs').rglob('events.jsonl')).read_text().splitlines()]
    human=next(i for i,e in enumerate(events) if e['event']=='ownership' and e['owner']=='human')
    first=next(i for i,e in enumerate(events) if e['event']=='action')
    assert human<first
