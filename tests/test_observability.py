import json
from pathlib import Path

from engine.contracts import Profile, Result
from engine.observability import action_info, error_info, explain
from engine import telemetry


def profile():
    return Profile.model_validate_json(Path('config/customer-service.json').read_text())


def test_only_reviewed_labels_and_errors_are_explained():
    p = profile()
    private = 'PRIVATE-PERSON-AND-ACCOUNT'
    unknown = action_info({'kind':'click', 'target':{'name':private}, 'reason':private}, p)
    assert unknown['title'] == 'Click control (label withheld)'
    assert private not in json.dumps(unknown)
    assert private not in json.dumps(error_info(private, p))
    assert error_info('Permission denied', p)['code'] == 'permission_denied'
    assert action_info({'kind':'click','target':{'name':'Edit mailing address'}},p)['title'] == 'Click Edit mailing address'


def test_old_evidence_does_not_invent_step_completion_or_timings():
    events = [json.loads(line) for line in Path('evidence/langsmith/permission-denied/events.jsonl').read_text().splitlines()]
    story = explain(events, profile())
    assert story['error_code'] == 'permission_denied'
    assert story['completed_actions'] is None
    assert story['protected_write_attempts'] is None
    assert story['attempted_actions'] == 4
    assert all(e['state'] == 'attempted' and 'duration_ms' not in e for e in story['timeline'] if e['operation']=='browser.action')


def test_interrupted_run_does_not_remain_running():
    events = [{'event':'run_started','task_title':'PRIVATE-TASK'}, {'event':'mode','mode':'replay'},
              {'event':'operation_started','operation':'page.check','title':'Check page for errors'}]
    story = explain(events, profile(), 'failure')
    assert story['status'] == 'failure'
    assert story['error_code'] == 'missing_result'
    assert story['timeline'][0]['state'] == 'completion_unknown'
    assert 'PRIVATE-TASK' not in json.dumps(story)


def test_failed_model_attempt_is_counted_without_inventing_tokens():
    events = [{'event':'mode','mode':'discovery'}, {'event':'model_request'},
              {'event':'run_finished','result':{'status':'failure','code':'PRIVATE-PROVIDER-ERROR'}}]
    story = explain(events, profile())
    assert story['model_calls'] == 1
    assert story['input_tokens'] == story['output_tokens'] == 0
    assert story['model_calls_basis'] == 'transport attempts'
    assert 'PRIVATE-PROVIDER-ERROR' not in json.dumps(story)


def test_model_choice_and_root_summary_export_without_raw_reason(trace_capture):
    @telemetry.traced('model.request', 'llm')
    def model():
        telemetry.model_sent('groq','test-model')
        return {'prompt_eval_count':5, 'eval_count':2, 'message':{'content':'PRIVATE-RESPONSE'}}
    @telemetry.traced('workflow.discovery')
    def run():
        telemetry.describe_workflow('Update mailing address',profile())
        model()
        telemetry.event('model_decision', {'decision':{'action':{'kind':'click','target':{'name':'Edit mailing address'},'reason':'PRIVATE-REASON'}}})
        telemetry.describe_result(explain([{'event':'mode','mode':'discovery'}, {'event':'run_finished','result':{'status':'failure','code':'Permission denied'}}], profile()))
        return Result(status='failure',code='Permission denied',run_id='test')
    run()
    trace = trace_capture[0]
    assert trace.record['name'] == 'Discover: Update mailing address'
    assert trace.spans[1]['outputs']['selected_action'] == 'Click Edit mailing address'
    assert trace.record['outputs']['error_code'] == 'permission_denied'
    assert trace.record['error'] == 'The application denied access to the requested operation.'
    assert 'PRIVATE-' not in json.dumps(trace.spans, default=str)
