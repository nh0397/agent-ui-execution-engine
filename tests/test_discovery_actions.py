from engine.contracts import WorkflowSpec
from engine.discovery import available_actions


def test_affordances_are_derived_from_observation_not_workflow():
    spec = WorkflowSpec(name="unrelated_order", description="Inspect order", inputs={"order_id": {}}, outputs={"status": {}}, success={"by": "text", "name": "Complete"})
    observation = {"controls": [
        {"name": "Order number", "role": "textbox", "readonly": False},
        {"name": "Find order", "role": "button", "readonly": False},
    ]}
    actions = available_actions(observation, spec, {})
    assert len(actions) == 2
    assert actions[0].input_key == "order_id"
    assert actions[1].target.name == "Find order"
    after_fill = available_actions(observation, spec, {}, {"Order number"})
    assert [a.kind for a in after_fill] == ["click"]


def test_read_only_controls_cannot_be_filled():
    spec = WorkflowSpec(name="other", description="Read status", inputs={}, outputs={"status": {}}, success={"by": "text", "name": "Complete"})
    observation = {"controls": [{"name": "Status", "role": "textbox", "readonly": True}]}
    assert [a.kind for a in available_actions(observation, spec, {})] == ["read"]
    assert available_actions(observation, spec, {"status": "Complete"}) == []


def test_native_constraints_exclude_invalid_binding_without_exposing_values():
    spec = WorkflowSpec(name="other", description="Inspect item", inputs={"code": {}, "description": {}}, outputs={}, success={"by": "text", "name": "Complete"})
    observation = {"controls": [{"name": "Item code", "role": "textbox", "readonly": False, "pattern": "[0-9]{3}"}]}
    actions = available_actions(observation, spec, {}, inputs={"code": "123", "description": "private-value"})
    assert [a.input_key for a in actions] == ["code"]
    assert "123" not in actions[0].model_dump_json()
    assert "private-value" not in actions[0].model_dump_json()


def test_output_contract_excludes_wrong_field_binding():
    spec = WorkflowSpec(name="other", description="Inspect item", inputs={"code": {}}, outputs={"code": {"equals_input": "code"}, "receipt": {"pattern": "R-[0-9]+"}}, success={"by": "text", "name": "Complete"})
    observation = {"controls": [{"name": "Result", "role": "textbox", "readonly": True}]}
    actions = available_actions(observation, spec, {}, inputs={"code": "123"}, read_values={"Result": "R-456"})
    assert [a.output_key for a in actions] == ["receipt"]
