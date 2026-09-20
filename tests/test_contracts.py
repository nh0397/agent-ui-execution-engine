import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from engine.contracts import Action, Profile
from engine.safety import Evidence, Policy, PolicyError


def test_fill_requires_parameter_reference():
    with pytest.raises(ValidationError):
        Action(kind="fill", target={"by": "label", "name": "Address"}, reason="Enter address")


def test_unknown_fields_rejected():
    with pytest.raises(ValidationError):
        Action(kind="click", target={"by": "text", "name": "Save"}, reason="Save", script="arbitrary code")


@pytest.mark.parametrize("url", ["https://evil.example/", "http://127.0.0.1:8000.evil.example/", "http://user:pass@127.0.0.1:8000/", "http://127.0.0.1:8000/admin"])
def test_policy_denies_destinations(url):
    policy = Policy(Profile.model_validate_json(Path("config/customer-service.json").read_text()))
    with pytest.raises(PolicyError):
        policy.url(url)


def test_redaction_is_recursive(tmp_path):
    evidence = Evidence(tmp_path / "run", ["secret-city"])
    evidence.event("check", nested={"items": ["secret-city", "prefix secret-city suffix"]})
    content = (tmp_path / "run/events.jsonl").read_text()
    assert "secret-city" not in content
    assert "[REDACTED]" in content
