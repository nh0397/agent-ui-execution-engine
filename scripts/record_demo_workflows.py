"""Record explicit scripted demonstrations through a real UI and add truthful run history.

This is automated demonstration authoring, not LLM discovery or human participation.
Run while the dashboard has no active jobs; restart it afterward to load CLI run history.
"""
import argparse
import json
import os
import time
import uuid
from pathlib import Path

from engine.api import LiveControl
from engine.contracts import Capability, Profile
from engine.recording import record
from engine.runtime import replay
from engine.surface import BrowserSurface


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--entry', default='http://127.0.0.1:8003')
    parser.add_argument('--storage', default='work/agent-workspace')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(root/'.browsers'))
    storage = Path(args.storage)
    for folder in ('runs', 'capabilities', 'drafts'): (storage/folder).mkdir(parents=True, exist_ok=True)
    profile = Profile.model_validate_json((root/'config/customer-service.json').read_text())
    profile.origins = [args.entry]
    examples = [
        ('Look up an account balance', [('link','Accounts'),('focus','Account ID'),('fill','account_id','AC-10000'),('button','Search accounts'),('link','Open account')],
         'Account balance verified', {'Verified account ID':'account_id','Account balance':'balance'}, {'account_id':'AC-10001'}),
        ('Update a mailing address', [('focus','Customer ID'),('fill','customer_id','C-1000'),('button','Search customers'),('link','Open customer'),('link','Edit mailing address'),('focus','Street address'),('fill','street','42 Demo Lane'),('focus','City'),('fill','city','Cedar Grove'),('focus','Postal code'),('fill','postal','40000'),('button','Review changes'),('button','Save address')],
         'Address updated', {'Saved customer ID':'customer_id','Saved street address':'street','Saved city':'city','Saved postal code':'postal','Confirmation reference':'confirmation_reference'}, {'customer_id':'C-1001','street':'84 Demo Lane','city':'Maple Harbor','postal':'40001'}),
        ('Freeze a debit card', [('link','Debit cards'),('focus','Card ID'),('fill','card_id','DC-1000'),('button','Search cards'),('button','Review freeze'),('button','Freeze card')],
         'Card frozen', {'Saved card ID':'card_id','Saved card status':'status','Card confirmation reference':'reference'}, {'card_id':'DC-1001'}),
    ]
    def save(job):
        (storage/f"job-{job['id']}.json").write_text(json.dumps(job, indent=2), encoding='utf-8')
    def job(mode, name, capability_id='example'):
        return {'id':str(uuid.uuid4()),'created':time.time(),'mode':mode,'status':'running','code':'starting',
                'profile':'Automated demonstration','capability_id':capability_id,'scenario':'normal',
                'approve_writes':True,'name':name+' (automated demonstration)','recording_actor':'automated_demo'}
    for name, gestures, heading, outputs, new_inputs in examples:
        control = LiveControl()
        class DemonstrationSurface(BrowserSurface):
            def pump_events(self):
                super().pump_events()
                if control.recording.get('error'): raise RuntimeError(control.recording['error'])
                if gestures:
                    item = gestures.pop(0)
                    if item[0] == 'fill': command = {'kind':'type','parameter_key':item[1],'text':item[2]}
                    else:
                        locator = self.page.get_by_label(item[1],exact=True) if item[0]=='focus' else self.page.get_by_role(item[0],name=item[1],exact=True)
                        locator.scroll_into_view_if_needed()
                        box = locator.bounding_box()
                        command = {'kind':'click','x':box['x']+box['width']/2,'y':box['y']+box['height']/2}
                else: command = {'kind':'finish','success_name':heading,'output_bindings':outputs}
                control.commands.put({**command,'operator_id':'automated-demonstration'})
        recording_job = job('recording', name)
        save(recording_job)
        draft = storage/'drafts'/f"{recording_job['id']}.json"
        result = record(name, name+'; recorded by an automated demonstration, not a human or LLM discovery.', profile,
                        args.entry, storage/'runs'/recording_job['id'], draft, control,
                        surface_factory=DemonstrationSurface, recording_actor='automated_demo')
        recording_job.update(status=result.status,code=result.code,run_id=result.run_id,finished=time.time())
        if result.status == 'success':
            cap = Capability.model_validate_json(draft.read_text())
            (storage/'capabilities'/f"{recording_job['id']}.json").write_text(cap.model_dump_json(indent=2),encoding='utf-8')
            recording_job.update(capability_id=recording_job['id'],code='Automated demonstration recorded and published')
        save(recording_job)
        print(json.dumps({'name':name,'recording':recording_job['id'],'status':result.status}),flush=True)
        if result.status != 'success': raise RuntimeError(result.code)
        replay_job = job('replay',name,recording_job['id']);save(replay_job)
        result = replay(cap,new_inputs,profile,args.entry,storage/'runs'/replay_job['id'],approve_writes=True)
        replay_job.update(status=result.status,code=result.code,run_id=result.run_id,finished=time.time());save(replay_job)
        print(json.dumps({'replay':replay_job['id'],'status':result.status,'actions':result.step}),flush=True)
        if result.status != 'success': raise RuntimeError(result.code)


if __name__ == '__main__': main()
