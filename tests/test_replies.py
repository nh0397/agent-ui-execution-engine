"""Reply formatting and privacy tests. Fixtures are not LLM discovery evidence."""
import json
from pathlib import Path

import pytest
from engine.contracts import Capability, Result, WorkflowSpec
from engine.replies import result_reply


def balance_capability():
    return Capability.model_validate({
        "name": "Check account balance", "description": "Read an account's ledger balance",
        "version": 1, "app": "customer-service", "app_version": "1", "discovery_run": "scripted-test",
        "inputs": {"account_id": {"pattern": "AC-[0-9]+"}},
        "outputs": {"returned_account": {"sensitive": True}, "amount": {"sensitive": True}},
        "success": {"by": "role", "role": "heading", "name": "Account balance verified"},
        "steps": [
            {"kind":"click", "target":{"by":"role","role":"link","name":"Accounts"}, "reason":"Scripted test"},
            {"kind":"fill", "target":{"by":"label","name":"Account ID"}, "input_key":"account_id", "reason":"Scripted test"},
            {"kind":"click", "target":{"by":"role","role":"button","name":"Search accounts"}, "reason":"Scripted test"},
            {"kind":"click", "target":{"by":"role","role":"link","name":"Open account"}, "reason":"Scripted test"},
            {"kind":"read", "target":{"by":"label","name":"Verified account ID"}, "output_key":"returned_account", "reason":"Scripted test"},
            {"kind":"read", "target":{"by":"label","name":"Account balance"}, "output_key":"amount", "reason":"Scripted test"},
        ],
    })


@pytest.mark.parametrize("balance,expected", [("4200.75","$4,200.75"), ("0.00","$0.00"), ("-12.50","$-12.50")])
def test_reply_uses_verified_balance_and_field_labels(balance, expected):
    result = Result(status="success", code="completed", run_id="test", outputs={"returned_account":"AC-4205","amount":balance})
    reply = result_reply(result, balance_capability())
    assert expected in reply and "USD" in reply and "AC-4205" in reply


@pytest.mark.parametrize("balance", ["[REDACTED]", "NaN", "", "perhaps 42", "Infinity"])
def test_unavailable_balance_is_never_invented(balance):
    result = Result(status="success", code="completed", run_id="test", outputs={"returned_account":"AC-4205","amount":balance})
    assert "$" not in result_reply(result, balance_capability())


def test_failure_and_business_outcome_never_claim_success():
    for status, code in [("failure","Permission denied"), ("business_outcome","Account not found")]:
        reply = result_reply(Result(status=status,code=code,run_id="test",outputs={"balance":"999"}), balance_capability())
        assert "couldn't" in reply and "Done" not in reply and "$" not in reply


def test_address_success_confirms_change_and_learning():
    spec = WorkflowSpec.model_validate_json(Path("config/address-workflow.json").read_text(encoding="utf-8"))
    result = Result(status="success",code="completed",run_id="test",outputs={"customer_id":"C-104"})
    assert result_reply(result,spec,"discovery") == "Done — I updated the mailing address for customer C-104. I've also saved the workflow so you can use it again."


def test_confirmation_only_keeps_outputs_verified_but_out_of_reply():
    cap=balance_capability().model_copy(update={'return_details':False})
    result=Result(status='success',code='completed',run_id='test',outputs={'returned_account':'AC-4205','amount':'4200.75'})
    assert result_reply(result,cap)=='Done — I completed and verified the task.'
    assert result.outputs['amount']=='4200.75'
    assert set(cap.outputs)=={'returned_account','amount'}
    failed=result.model_copy(update={'status':'failure','code':'Permission denied'})
    assert 'Done' not in result_reply(failed,cap)


def test_requested_address_details_use_verified_values_only():
    spec=WorkflowSpec.model_validate_json(Path('config/address-workflow.json').read_text(encoding='utf-8'))
    spec.return_details=True
    result=Result(status='success',code='completed',run_id='test',outputs={'customer_id':'C-104','confirmation_reference':'UPD-ABC','street':'75 Pine Street','city':'Fremont','postal':'94538'})
    reply=result_reply(result,spec,'discovery')
    assert 'UPD-ABC' in reply and '75 Pine Street, Fremont, 94538' in reply and 'saved the workflow' in reply
    result.outputs['street']='[REDACTED]'
    assert 'Saved address:' not in result_reply(result,spec)
