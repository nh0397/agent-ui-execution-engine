"""Human-authored capabilities. No model calls; raw example values stay in memory."""
import re
import time
import uuid
from pathlib import Path

from playwright.sync_api import Error as BrowserError

from engine.contracts import Action, Capability, Parameter, Result, Target
from engine.runtime import validate_values
from engine.safety import Evidence, Policy, PolicyError
from engine.surface import BrowserSurface


class CaptureJournal:
    def __init__(self, surface, evidence):
        self.surface, self.evidence = surface, evidence
        self.entries = []

    def capture(self, phase):
        if len(self.entries) >= 200:
            raise PolicyError("Recording limit reached; finish or abort")
        name = f"step-{len(self.entries)+1:03d}-{phase}.png"
        for attempt in range(3):
            try:
                image = self.surface.redacted_frame()
                break
            except BrowserError as exc:
                if attempt == 2 or not any(term in str(exc).lower() for term in ("context was destroyed", "cannot find context", "frame was detached")):
                    raise
                # Retry observation only, never the human's state-changing gesture.
                self.surface.pump_events()
        (self.evidence.directory / name).write_bytes(image)
        return name

    def append(self, command, before, after, action=None):
        entry = self.evidence.clean({"number": len(self.entries)+1, "kind": command["kind"],
            "operator_id": command.get("operator_id"), "action": action.model_dump() if action else None,
            "before": before, "after": after})
        self.entries.append(entry)
        self.evidence.save("recording.json", self.entries)
        lines = ["# Human workflow recording", "", "Screenshots are redacted before persistence. Text values are replaced with parameter references.", ""]
        for item in self.entries:
            a = item['action']
            title = f"{a['kind']} {a['target']['name']}" if a else item['kind'] + " (operator gesture; see screenshots)"
            # Escape markdown and redact all text before writing documentation.
            title = re.sub(r'([\\`*_{}\[\]<>#])', r'\\\1', title)
            lines += [f"## Step {item['number']}: {title}", ""]
            if a and a.get('input_key'):
                lines += [f"Input parameter: `{a['input_key']}`", ""]
            lines += [f"![Before]({item['before']})", "", f"![After]({item['after']})", ""]
        (self.evidence.directory / 'WORKFLOW.md').write_text(self.evidence.clean('\n'.join(lines)), encoding='utf-8')
        self.evidence.event("human_step", **entry)


def record(name, description, profile, entry, directory, draft_path, control, **unused):
    run_id = str(uuid.uuid4())
    evidence = Evidence(Path(directory) / run_id, [])
    surface = BrowserSurface(Policy(profile), evidence)
    surface.owner = 'human'
    actions, inputs, values = [], {}, {}
    journal = CaptureJournal(surface, evidence)
    result = Result(status='failure', code='Recording aborted', run_id=run_id, human_assisted=True)
    evidence.event('run_started', run_id=run_id, session_id=surface.session_id, capability=name)
    evidence.event('mode', mode='recording', source='human')
    def publish():
        control.frame = surface.frame()
        control.state = {'owner':'human','session_id':surface.session_id,'step':len(actions)}
        observation = surface.observe()
        control.recording = {'steps':journal.entries, 'parameters':{k:p.model_dump() for k,p in inputs.items()},
            'headings':[c['name'] for c in observation['controls'] if c['role']=='heading'],
            'outputs':[c['name'] for c in observation['controls'] if c['readonly']], 'error':''}
    try:
        surface.open(entry)
        state = surface.observe()
        if state['app'] != profile.app or state['app_version'] != profile.version:
            raise PolicyError('Application compatibility check failed')
        evidence.event('ownership', owner='human', session_id=surface.session_id)
        publish()
        until = time.monotonic()+1800
        while time.monotonic() < until and not control.cancel.is_set():
            surface.pump_events()
            if control.commands.empty():
                continue
            command = control.commands.get_nowait()
            try:
                if command['kind']=='finish':
                    success=Target(by='role',role='heading',name=command['success_name'])
                    if not surface.visible(success):
                        raise PolicyError('Select the visible terminal success heading')
                    outputs, extracted, reads = {}, {}, []
                    for label,key in command['output_bindings'].items():
                        if not re.fullmatch(r'[a-z][a-z0-9_]{0,49}',key):
                            raise PolicyError('Output keys must use lowercase letters, numbers and underscores')
                        if key in outputs:
                            raise PolicyError('Output keys must be unique')
                        target=Target(by='label',name=label)
                        if not surface.visible(target) or not surface.target(target).evaluate('e=>!!e.readOnly'):
                            raise PolicyError('Outputs must be visible readonly result fields')
                        value=surface.target(target).input_value()
                        outputs[key]=Parameter(sensitive=True, equals_input=key if key in inputs else None)
                        if key in values and values[key] != value:
                            raise PolicyError('Saved output does not match its input parameter')
                        extracted[key]=value
                        reads.append(Action(kind='read', target=target,output_key=key,reason='Extract human-selected verified output'))
                    if not outputs or not actions:
                        raise PolicyError('Record actions and select at least one output before finishing')
                    validate_values(outputs,extracted)
                    cap=Capability(name=name,description=description,inputs=inputs,outputs=outputs,success=success,
                        version=1,app=profile.app,app_version=profile.version,steps=actions+reads,
                        discovery_run=run_id,source='human')
                    text=cap.model_dump_json(indent=2)
                    if evidence.clean(text)!=text:
                        raise PolicyError('A target contains example data; use a stable label')
                    path=Path(draft_path);path.parent.mkdir(parents=True,exist_ok=True)
                    with path.open('x',encoding='utf-8') as f:f.write(text)
                    evidence.save('draft.json',cap.model_dump())
                    result=Result(status='success',code='Recording ready for review',run_id=run_id,step=len(actions),human_assisted=True)
                    break
                action=None
                kind=command['kind']
                if kind=='type':
                    key=command.get('parameter_key','')
                    if not re.fullmatch(r'[a-z][a-z0-9_]{0,49}',key):
                        raise PolicyError('Choose a parameter name before entering a field')
                    target,descriptor=surface.recording_target(command)
                    if not descriptor['editable']:
                        raise PolicyError('Select an editable text field first')
                    value=command['text']
                    parameter=Parameter(sensitive=True,pattern=descriptor['pattern'])
                    validate_values({key:parameter},{key:value})
                    if key in values and values[key]!=value:
                        raise PolicyError('Use a new parameter name for a different example value')
                    # All human examples are sensitive; learned selectors must never contain them.
                    evidence.secrets.append(value)
                    evidence.secrets.sort(key=len,reverse=True)
                    before=journal.capture('before')
                    surface.target(target).fill(value)
                    inputs[key]=parameter;values[key]=value
                    action=Action(kind='fill',target=target,input_key=key,reason='Human entered parameter')
                elif kind=='click' or (kind=='key' and command.get('key')=='Enter'):
                    target,descriptor=surface.recording_target(command)
                    if not descriptor['field'] and descriptor['role'] not in ('button','link'):
                        raise PolicyError('Only labeled fields, buttons and links can be recorded')
                    if kind=='key' and descriptor['field']:
                        raise PolicyError('Click the named submit button so it can be replayed reliably')
                    before=journal.capture('before')
                    surface.target(target).click()
                    if not descriptor['field']:
                        action=Action(kind='click',target=target,reason='Human activated control')
                elif kind=='scroll' or (kind=='key' and command.get('key')=='Tab'):
                    before=journal.capture('before')
                    surface.operator_action(command)
                else:
                    raise PolicyError('Use clicks, Tab, scrolling, or parameterized field entry while recording')
                surface.assert_policy()
                after=journal.capture('after')
                journal.append(command,before,after,action)
                if action:actions.append(action)
                publish()
            except (PolicyError,ValueError) as exc:
                control.recording['error']=evidence.clean(str(exc))
                evidence.event('recording_command_rejected',reason=str(exc))
                if surface.blocked:
                    raise
        else:
            result.code='Recording aborted or timed out'
    except Exception as exc:
        result.code=type(exc).__name__
        try:surface.snapshot()
        except Exception:pass
    finally:
        control.recording['steps']=journal.entries
        evidence.save('result.json',result.model_dump())
        evidence.event('run_finished',result=result.model_dump())
        surface.close()
    return result
