"""Scripted fixtures test execution; these are not LLM discovery evidence."""
import json
import os
import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from demo.app import create_app
from engine.contracts import Action, Capability, Profile, WorkflowSpec
from engine.runtime import replay


def fixture_capability():
    spec = WorkflowSpec.model_validate_json(Path("config/address-workflow.json").read_text())
    def click(role, name):
        return Action(kind="click", target={"by": "role", "role": role, "name": name}, reason="Scripted test fixture")
    def fill(name, key):
        return Action(kind="fill", target={"by": "label", "name": name}, input_key=key, reason="Scripted test fixture")
    steps = [fill("Customer ID", "customer_id"), click("button", "Search customers"), click("link", "Open customer"), click("link", "Edit mailing address"), fill("Street address", "street"), fill("City", "city"), fill("Postal code", "postal"), click("button", "Review changes"), click("button", "Save address")]
    for label, key in [("Saved customer ID", "customer_id"), ("Confirmation reference", "confirmation_reference"), ("Saved street address", "street"), ("Saved city", "city"), ("Saved postal code", "postal")]:
        steps.append(Action(kind="read", target={"by": "label", "name": label}, output_key=key, reason="Scripted test verification"))
    return Capability(**spec.model_dump(), version=1, app="customer-service", app_version="1", steps=steps, discovery_run="scripted-test-fixture-not-discovery")


@pytest.fixture
def server(tmp_path):
    running = []
    def start(scenario):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        config = uvicorn.Config(create_app(tmp_path / f"{port}.db", scenario), log_level="error", access_log=False)
        service = uvicorn.Server(config)
        thread = threading.Thread(target=service.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        deadline = time.monotonic() + 10
        while not service.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("Test server failed to start")
            time.sleep(0.01)
        running.append((service, thread, sock))
        return f"http://127.0.0.1:{port}"
    yield start
    for service, thread, sock in running:
        service.should_exit = True
        thread.join(timeout=5)
        sock.close()


@pytest.mark.parametrize("scenario,customer,status,code", [
    ("normal", "C-205", "success", "completed"),
    ("transient", "C-205", "success", "completed"),
    ("uncertain-save", "C-205", "success", "completed"),
    ("normal", "C-999", "business_outcome", "Customer not found"),
    ("permission-denied", "C-205", "failure", "Permission denied"),
    ("session-expired", "C-205", "failure", "Human intervention requires a headed run"),
])
def test_replay_browser_scenarios(tmp_path, server, scenario, customer, status, code, monkeypatch):
    import httpx
    def forbidden_model_transport(*args, **kwargs):
        raise AssertionError("Replay must not call the model HTTP transport")
    monkeypatch.setattr(httpx.Client, "send", forbidden_model_transport)
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(Path(".browsers").resolve()))
    origin = server(scenario)
    profile = Profile.model_validate_json(Path("config/customer-service.json").read_text())
    profile.origins = [origin]
    inputs = json.loads(Path("config/inputs-b.json").read_text())
    inputs["customer_id"] = customer
    result = replay(fixture_capability(), inputs, profile, origin, tmp_path / "runs", approve_writes=True)
    assert (result.status, result.code) == (status, code), result
    if status == "success":
        assert result.outputs["customer_id"] == customer
        assert result.outputs["street"] == inputs["street"]
    for path in (tmp_path / "runs").rglob("*.json*"):
        content = path.read_text()
        assert inputs["street"] not in content
        assert inputs["city"] not in content
    if status != "success":
        assert list((tmp_path / "runs").rglob("failure-snapshot.json"))


def test_risky_write_not_implicitly_approved(tmp_path, server):
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(Path(".browsers").resolve()))
    origin = server("normal")
    profile = Profile.model_validate_json(Path("config/customer-service.json").read_text())
    profile.origins = [origin]
    result = replay(fixture_capability(), json.loads(Path("config/inputs-b.json").read_text()), profile, origin, tmp_path / "runs")
    assert result.status == "failure"
    assert result.code == "Human intervention requires a headed run"
    import sqlite3
    with sqlite3.connect(next(tmp_path.glob("*.db"))) as conn:
        assert conn.execute("SELECT count(*) FROM updates").fetchone()[0] == 0


def test_wrong_output_binding_does_not_pass_success(tmp_path, server):
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(Path(".browsers").resolve()))
    origin = server("normal")
    profile = Profile.model_validate_json(Path("config/customer-service.json").read_text())
    profile.origins = [origin]
    capability = fixture_capability()
    capability.steps[-3].target.name = "Saved city"
    result = replay(capability, json.loads(Path("config/inputs-b.json").read_text()), profile, origin, tmp_path / "runs", approve_writes=True)
    assert result.status == "failure"
    assert result.code == "Extracted output does not match its declared input"


def test_discovery_dead_end_requests_real_handoff_without_publishing(tmp_path, server, monkeypatch):
    from engine.api import LiveControl
    from engine.discovery import discover
    import engine.discovery as discovery
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(Path(".browsers").resolve()))
    origin = server("normal")
    profile = Profile.model_validate_json(Path("config/customer-service.json").read_text())
    profile.origins = [origin]
    control = LiveControl()
    control.commands.put({"kind": "abort", "operator_id": "scripted-test"})
    monkeypatch.setattr(discovery, "available_actions", lambda *a, **k: [])
    artifact = tmp_path / "must-not-exist.json"
    result = discover(WorkflowSpec.model_validate_json(Path("config/address-workflow.json").read_text()),
        json.loads(Path("config/inputs-b.json").read_text()), profile, origin, tmp_path / "runs",
        "unused-no-model-call", "Update the address", artifact, control=control)
    assert result.status == "failure" and result.human_assisted
    assert not artifact.exists()
    events = [json.loads(line) for line in next((tmp_path / "runs").rglob("events.jsonl")).read_text().splitlines()]
    assert any(e["event"] == "intervention_requested" for e in events)
    assert any(e["event"] == "ownership" and e["owner"] == "human" for e in events)
    assert not any(e["event"] == "model_decision" for e in events)


def test_unexpected_dialog_stops_and_sensitive_snapshot_is_clean(tmp_path, server):
    from engine.runtime import Runtime
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(Path(".browsers").resolve()))
    origin = server("normal")
    profile = Profile.model_validate_json(Path("config/customer-service.json").read_text())
    profile.origins = [origin]
    runtime = Runtime(fixture_capability(), json.loads(Path("config/inputs-b.json").read_text()), profile, origin, tmp_path / "runs")
    try:
        runtime.surface.page.evaluate("""() => {
          const t=document.createElement('textarea');t.textContent='PRIVATE-TEXTAREA-CANARY';document.body.append(t);
          const n=document.createElement('div');n.dataset.sensitive='true';n.textContent='PRIVATE-NODE-CANARY';document.body.append(n);
          alert('PRIVATE-DIALOG-CANARY');
        }""")
        from engine.safety import PolicyError
        with pytest.raises(PolicyError, match="Unexpected browser dialog"):
            runtime.surface.assert_policy()
        result = runtime.result(PolicyError("Unexpected browser dialog"))
        runtime.close(result)
        text = "".join(p.read_text() for p in (tmp_path / "runs").rglob("*.json*"))
        assert 'PRIVATE-' not in text
        assert 'Unexpected browser dialog' in text
    except BaseException:
        try:
            runtime.surface.close()
        except Exception:
            pass
        raise


def test_session_expiry_restores_same_session_with_scripted_operator(tmp_path, server):
    from engine.api import LiveControl
    from engine.surface import BrowserSurface
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(Path(".browsers").resolve()))
    origin = server("session-expired")
    profile = Profile.model_validate_json(Path("config/customer-service.json").read_text())
    profile.origins = [origin]
    control = LiveControl()
    class ScriptedOperatorSurface(BrowserSurface):
        def pump_events(self):
            super().pump_events()
            if self.page.get_by_role("button", name="Restore session").count():
                self.page.get_by_role("button", name="Restore session").click()
                self.page.get_by_label("Customer ID", exact=True).fill("C-205")
                self.page.get_by_role("button", name="Search customers").click()
                control.commands.put({"kind": "resume", "operator_id": "scripted-test"})
    result = replay(fixture_capability(), json.loads(Path("config/inputs-b.json").read_text()),
        profile, origin, tmp_path / "runs", approve_writes=True, control=control,
        surface_factory=ScriptedOperatorSurface)
    assert result.status == "success", result
    assert result.human_assisted
    events = [json.loads(line) for line in next((tmp_path / "runs").rglob("events.jsonl")).read_text().splitlines()]
    owners = [e for e in events if e["event"] == "ownership"]
    assert [e["owner"] for e in owners] == ["human", "automation"]
    assert len({e["session_id"] for e in owners}) == 1
    assert any(e["event"] == "human_action" for e in events)


def test_live_screencast_updates_between_workflow_actions(tmp_path, server):
    from engine.surface import BrowserSurface
    from engine.safety import Evidence, Policy
    os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(Path('.browsers').resolve()))
    origin = server('normal')
    profile = Profile.model_validate_json(Path('config/customer-service.json').read_text())
    profile.origins = [origin]
    surface = BrowserSurface(Policy(profile), Evidence(tmp_path/'frames', []))
    frames = []
    try:
        surface.start_live_frames(frames.append)
        surface.open(origin)
        surface.page.evaluate("setTimeout(() => document.body.style.background = 'red', 150)")
        for _ in range(10): surface.pump_events()
        assert len(set(frames)) >= 2
        assert all(frame.startswith(bytes([255,216])) for frame in frames)
        assert not list(tmp_path.rglob('*.jpg'))
    finally:
        surface.close()
