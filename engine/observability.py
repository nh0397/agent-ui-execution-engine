"""Readable explanations derived from execution evidence, without another LLM.

Only reviewed profile labels and fixed engine messages may enter the explanation.
Unknown page text, targets, model reasons, exception text, and values stay private.
"""
import datetime as dt
import functools
import time

from engine import telemetry


ERRORS = {
    'Run cancelled by operator': ('cancelled', 'The operator stopped this run.', 'Start a new run when you are ready.'),
    'Recovery budget exhausted': ('recovery_exhausted', 'The allowed recovery attempts did not resolve the problem.', 'Inspect the application before retrying.'),
    'Success checkpoint not reached': ('verification_failed', 'The expected result page was not reached.', 'Inspect the final page and the saved workflow.'),
    'Extracted output does not match its declared input': ('output_mismatch', 'A result value did not match the requested input.', 'Check the saved state before making another change.'),
    'Saved output does not match requested input': ('output_mismatch', 'A saved value did not match the request.', 'Check the saved state before making another change.'),
    'Application compatibility check failed': ('incompatible_app', 'The application did not match the expected version.', 'Check the application profile before running again.'),
    'Human intervention requires a headed run': ('handoff_unavailable', 'The run needed a person, but no human control channel was available.', 'Run through the workspace or enable the CLI operator view.'),
    'Intervention aborted or expired': ('handoff_ended', 'Human review was cancelled or timed out.', 'Inspect the application state before starting again.'),
    'Resume checkpoint not satisfied': ('resume_rejected', 'The page was not at the required checkpoint for resuming.', 'Return to the requested checkpoint before resuming.'),
    'Run deadline exceeded': ('deadline', 'The run reached its time limit.', 'Inspect the application before starting again.'),
    'Discovery step limit exceeded': ('step_limit', 'The model used its allowed steps without completing the task.', 'Review the recorded steps and the task contract.'),
    'Invalid model action choice': ('invalid_model_action', 'The model selected an action that was not available.', 'Review the discovery evidence before retrying.'),
    'TimeoutError': ('timeout', 'A browser operation timed out.', 'Check the current page before retrying a possible write.'),
    'Recording aborted or timed out': ('recording_stopped', 'The recording stopped without a verified workflow.', 'Start another recording or inspect the captured steps.'),
    'Result evidence missing': ('missing_result', 'The run ended before recording a final result.', 'Inspect the local evidence and the application before retrying.'),
    'Target is ambiguous': ('ambiguous_target', 'More than one control matched the requested target.', 'Review the element target before retrying.'),
    'Destination origin is not allowed': ('blocked_destination', 'Navigation was blocked by the allowed-domain policy.', 'Check the destination and application policy.'),
    'Destination route is not allowed': ('blocked_route', 'Navigation was blocked by the allowed-route policy.', 'Check the destination and application policy.'),
}


def error_info(code, profile):
    reviewed = profile.trace_labels.errors.get(code)
    if reviewed:
        return reviewed.model_dump()
    values = ERRORS.get(code, ('unclassified', 'The run stopped with an unclassified error. Its text is kept in local evidence.', 'Open the local evidence to investigate.'))
    return dict(zip(('code', 'explanation', 'next_step'), values))


def action_info(action, profile):
    if hasattr(action, 'model_dump'):
        action = action.model_dump()
    action = action or {}
    kind = action.get('kind')
    verb = {'click': 'Click', 'fill': 'Fill', 'read': 'Read', 'check': 'Check'}.get(kind, 'Operate')
    name = (action.get('target') or {}).get('name')
    reviewed = name in profile.trace_labels.controls
    return {'title': f'{verb} {name if reviewed else "control (label withheld)"}',
            'purpose': profile.trace_labels.controls.get(name, 'Perform the recorded UI operation. This label has not been reviewed for export.'),
            'action_kind': kind if kind in {'click', 'fill', 'read', 'check'} else 'unknown'}


def workflow_title(spec, profile):
    return profile.trace_labels.workflows.get(spec.name) or profile.trace_labels.workflows.get(spec.success.name) or 'Browser workflow'


def observed(operation):
    """Time actual runtime operations locally and in optional LangSmith spans."""
    def decorate(fn):
        @functools.wraps(fn)
        def call(runtime, *args, **kwargs):
            info = {'title': {'page.check': 'Check page for errors', 'result.verify': 'Verify the final result',
                              'human.takeover': 'Wait for human review'}.get(operation, operation),
                    'purpose': {'page.check': 'Check for known business outcomes, access problems, or recoverable errors.',
                                'result.verify': 'Check the success page and every required output against the contract.',
                                'human.takeover': 'Keep the browser open while a person reviews or repairs the task.'}.get(operation, '')}
            if operation in {'browser.action', 'browser.recovery'}:
                info = action_info(args[0], runtime.profile)
                if operation == 'browser.recovery': info['title'] = 'Recover: ' + info['title']
            if operation == 'browser.action': info['action_number'] = runtime.step + 1
            start = time.monotonic()
            state, problem = 'completed', None
            with telemetry.operation(operation, 'tool') as span:
                if span:
                    span.record['name'] = info['title']
                    span.record['extra']['metadata']['operation'] = operation
                    span.record['outputs'].update(info)
                runtime.evidence.event('operation_started', operation=operation, **info)
                try:
                    result = fn(runtime, *args, **kwargs)
                    if operation == 'browser.action' and runtime.step < info['action_number']:
                        info['purpose'] += ' This step completed after human review.'
                    if span: span.finish(result)
                    return result
                except Exception as exc:
                    state = 'business_outcome' if type(exc).__name__ == 'BusinessOutcome' else 'failure'
                    problem = error_info(str(exc), runtime.profile)
                    if span and state == 'business_outcome': span.expected_outcome = True
                    if span and state == 'failure': span.record['error'] = problem['explanation']
                    raise
                finally:
                    details = {**info, 'operation': operation, 'state': state,
                               'duration_ms': round((time.monotonic()-start)*1000, 2)}
                    if problem: details.update(problem)
                    if span: span.record['outputs'].update(details)
                    runtime.evidence.event('operation_finished', **details)
        return call
    return decorate


def explain(events, profile, fallback_status=None):
    """Create a deterministic run story, including a truthful fallback for old runs."""
    start = next((e for e in events if e['event'] == 'run_started'), {})
    end = next((e for e in reversed(events) if e['event'] == 'run_finished'), {})
    mode = next((e.get('mode') for e in events if e['event'] == 'mode'), 'workflow')
    result = end.get('result') or {}
    if not result and fallback_status == 'failure':
        result = {'status':'failure', 'code':'Result evidence missing'}
    state = result.get('status', 'running')
    title = start.get('task_title') or profile.trace_labels.workflows.get(start.get('capability')) or 'Browser workflow'
    # task_title is emitted by our reviewed vocabulary, but older/imported logs are untrusted.
    if title not in set(profile.trace_labels.workflows.values()) | {'Browser workflow', 'Record a browser workflow'}:
        title = 'Browser workflow'
    timeline = []
    pending = []
    for event in events:
        if event['event'] == 'operation_started': pending.append(event)
        if event['event'] == 'operation_finished':
            # Start/finish are nested, so the newest matching start owns this finish.
            for i in range(len(pending)-1, -1, -1):
                if pending[i]['operation'] == event['operation']:
                    pending.pop(i)
                    break
            timeline.append({k:event[k] for k in ('title','purpose','operation','state','duration_ms','action_number','explanation','next_step') if k in event})
        elif event['event'] == 'condition':
            info = error_info(event.get('code'), profile)
            timeline.append({'title': info['explanation'], 'operation': 'condition',
                             'state': event.get('category'), 'next_step': info['next_step']})
        elif event['event'] == 'ownership':
            timeline.append({'title': 'Human has control' if event.get('owner') == 'human' else 'Automation has control', 'state':'completed', 'operation':'ownership'})
        elif event['event'] == 'human_step':
            info = action_info(event.get('action'), profile) if event.get('action') else {'title':'Human browser gesture','purpose':'See the redacted recording for details.'}
            timeline.append({**info, 'state':'completed','operation':'human.action'})
    for event in pending:
        timeline.append({k:event[k] for k in ('title','purpose','operation','action_number') if k in event} | {'state': 'running' if state == 'running' else 'completion_unknown'})
    timed = any(e['event'] == 'operation_started' for e in events)
    if not timed:
        # Old action events record dispatch, not proof that the operation completed.
        timeline = [{**action_info(e.get('action'), profile), 'state':'attempted', 'operation':'browser.action'}
                    for e in events if e['event'] == 'action'] + timeline
    actions = [e for e in timeline if e.get('operation') == ('human.action' if mode == 'recording' else 'browser.action')]
    last = next((e['title'] for e in reversed(actions) if e['state'] == 'completed'), None)
    failure = next((e['title'] for e in reversed(timeline) if e.get('state') == 'failure' and e.get('operation') != 'condition'), None)
    problem = error_info(result.get('code'), profile) if state in {'failure','business_outcome'} else None
    requests = [e for e in events if e['event'] == 'model_request']
    decisions = [e for e in events if e['event'] == 'model_decision']
    calls = len(requests) if requests else (len(decisions) if mode == 'discovery' else 0)
    recorded_check = next((e for e in reversed(events) if e['event'] == 'recording_verified'), None)
    verified = bool(recorded_check) or any(e['event'] == 'operation_finished' and e.get('operation') == 'result.verify' and e.get('state') == 'completed' for e in events)
    protected = sum(e['event'] == 'protected_write_attempted' for e in events)
    human = bool(result.get('human_assisted')) or any(e['event'] == 'ownership' and e.get('owner') == 'human' for e in events)
    effects = ('A person had control. Review the recorded human actions before retrying.' if human else
               'A protected write was attempted. Check the saved state before retrying.' if protected else
               'No protected write was attempted.' if timed else 'This older run does not record protected write attempts separately.')
    if state == 'success':
        summary = 'The workflow completed and the result passed its checks.' if mode != 'recording' else 'The recording passed its checks and is ready for review before publication.'
        next_step = 'You can reuse this workflow with new inputs.' if mode != 'recording' else 'Review and publish the captured workflow.'
    elif problem:
        summary, next_step = problem['explanation'], problem['next_step']
    else:
        summary, next_step = 'The workflow is still running.', 'Watch the current step or request control.'
    elapsed = None
    if start.get('time') and end.get('time'):
        elapsed = round((dt.datetime.fromisoformat(end['time']) - dt.datetime.fromisoformat(start['time'])).total_seconds()*1000, 2)
    return {'task':title, 'mode':mode, 'status':state, 'summary':summary, 'next_step':next_step,
            'error_code':problem['code'] if problem else None, 'elapsed_ms':elapsed,
            'completed_actions':sum(e['state']=='completed' for e in actions) if timed or mode == 'recording' else None,
            'attempted_actions':len(actions), 'last_completed_action':last, 'stopped_at':failure,
            'model_calls':calls, 'model_calls_basis':'transport attempts' if requests or mode != 'discovery' else 'recorded successful decisions only',
            'input_tokens':sum(e.get('prompt_tokens') or 0 for e in decisions),
            'output_tokens':sum(e.get('output_tokens') or 0 for e in decisions),
            'outputs_count':recorded_check['outputs_count'] if recorded_check else len(result.get('outputs') or {}), 'verification_passed':verified if timed or recorded_check else None,
            'human_assisted':human, 'protected_write_attempts':protected if timed else None,
            'write_note':effects, 'timeline':timeline,
            'limitations':'Customer values, raw model messages, and unreviewed labels are withheld. Token totals include reported successful responses. Durations of nested operations overlap.'}
