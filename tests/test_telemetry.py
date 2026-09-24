import asyncio
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from engine import telemetry as t
from engine.contracts import Result


@pytest.fixture
def captured(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-private-key")
    monkeypatch.setenv("LANGSMITH_PROJECT", "test")
    monkeypatch.setenv("LANGSMITH_TRACE_LIMIT", "100")
    monkeypatch.setenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")
    spans = []
    monkeypatch.setattr(t, "_submit", spans.append)
    return spans


def test_disabled_and_invalid_settings_never_export(monkeypatch):
    monkeypatch.setattr(t, "_make_client", lambda cfg: pytest.fail("No client allowed"))
    @t.traced("test")
    def task(): return "unchanged"
    assert task() == "unchanged"
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_TRACE_LIMIT", "bad")
    assert task() == "unchanged"
    monkeypatch.setenv("LANGSMITH_TRACE_LIMIT", "10")
    monkeypatch.setenv("LANGSMITH_ENDPOINT", "https://attacker.example")
    assert task() == "unchanged"


def test_hierarchy_usage_and_privacy(captured):
    conversation = str(uuid.uuid4())
    @t.traced("model.request", "llm")
    def model(secret):
        t.model_sent("groq", "openai/gpt-oss-20b")
        return {"message": {"content": secret}, "prompt_eval_count": 10, "eval_count": 2}
    @t.traced("workflow.discovery")
    def task(secret):
        model(secret)
        t.event("action", {"action": {"kind": "fill", "target": {"name": secret}, "reason": secret}, "text": secret})
        t.event("observation", {"state": {"controls": [{"name": secret}], "url": secret}})
        t.event("ownership", {"owner": "human", "operator_id": secret})
        return Result(status="success", code=secret, run_id=str(uuid.uuid4()), outputs={"balance": secret})
    with t.bind_context(conversation_id=conversation):
        result = task("Sensitive street, account and API secret")
    assert result.status == "success"
    root = captured[0]
    serialized = json.dumps(root.spans, default=str)
    assert "Sensitive" not in serialized and "test-private-key" not in serialized
    assert root.spans[1]["parent_run_id"] == root.id
    assert root.spans[1]["outputs"]["usage_metadata"]["total_tokens"] == 12
    assert root.record["outputs"]["model_calls"] == 1
    assert root.record["extra"]["metadata"]["session_id"] == conversation
    assert root.record["events"][0]["kwargs"] == {"kind": "fill"}


def test_monthly_reservations_are_atomic_and_persistent(captured, monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACE_LIMIT", "2")
    @t.traced("test")
    def task(): return 17
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(lambda _: task(), range(8))) == [17]*8
    assert len(captured) == 2
    assert t.status()["traces_this_month"] == 2
    assert task() == 17
    assert len(captured) == 2


def test_span_limit_and_exception_preserve_behavior(captured, monkeypatch):
    monkeypatch.setattr(t, "MAX_SPANS", 3)
    @t.traced("child")
    def child(): return None
    @t.traced("root")
    def task():
        for _ in range(10): child()
        raise ValueError("Private exception contents")
    with pytest.raises(ValueError, match="Private exception"):
        task()
    root = captured[0]
    assert len(root.spans) == 3 and root.record["outputs"]["omitted_spans"] == 8
    assert "Private" not in json.dumps(root.spans, default=str)


def test_async_requests_do_not_mix_conversations(captured):
    @t.traced("chat")
    async def task():
        await asyncio.sleep(.005)
        return {"supported": True}
    async def one(id):
        with t.bind_context(conversation_id=id): await task()
    ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    async def both(): await asyncio.gather(*(one(id) for id in ids))
    asyncio.run(both())
    assert {s.record["extra"]["metadata"]["session_id"] for s in captured} == set(ids)
    assert all("parent_run_id" not in s.record for s in captured)


def test_failed_export_keeps_result_and_safe_status(captured, monkeypatch):
    @t.traced("task")
    def task(): return {"status": "success"}
    result = task()
    def unavailable(cfg, on_error=None): raise RuntimeError("API key and request text must not leak")
    monkeypatch.setattr(t, "_make_client", unavailable)
    t._export(captured[0])
    state = t.lookup(captured[0].id)
    assert state["state"] == "failed" and "API key" not in json.dumps(state)
    assert result == {"status": "success"}


def test_sdk_swallowed_failures_are_not_reported_as_exported(captured, monkeypatch):
    @t.traced("task")
    def task(): return 42
    task()
    class Client:
        def __init__(self, cfg, on_error): self.on_error = on_error
        def batch_ingest_runs(self, **kwargs): self.on_error(RuntimeError("private detail"))
        def read_run(self, id): pytest.fail("A failed export cannot be confirmed")
        def close(self): pass
    monkeypatch.setattr(t, "_make_client", Client)
    t._export(captured[0])
    assert t.lookup(captured[0].id)["state"] == "failed"


def test_success_needs_readback_and_valid_link(captured, monkeypatch):
    @t.traced("task")
    def task(): return 42
    task()
    class Client:
        def __init__(self, cfg, on_error): pass
        def batch_ingest_runs(self, **kwargs): pass
        def read_run(self, id): return object()
        def get_run_url(self, **kwargs): return "https://smith.langchain.com/test/run"
        def close(self): pass
    monkeypatch.setattr(t, "_make_client", Client)
    t._export(captured[0])
    assert t.lookup(captured[0].id)["state"] == "exported"
    monkeypatch.setattr(Client, "get_run_url", lambda *args, **kwargs: "https://attacker.example")
    monkeypatch.setattr(t.time, "sleep", lambda _: None)
    t._export(captured[0])
    assert t.lookup(captured[0].id)["state"] == "unconfirmed"
    assert t.lookup(captured[0].id)["url"] is None


def test_broken_trace_bookkeeping_cannot_change_results(captured, monkeypatch):
    def broken(*args, **kwargs): raise RuntimeError("trace bookkeeping failed")
    monkeypatch.setattr(t.Span, "_finish", broken)
    monkeypatch.setattr(t, "_submit", broken)
    @t.traced("task")
    def task(): return 42
    @t.traced("task")
    def failing(): raise ValueError("original error")
    assert task() == 42
    with pytest.raises(ValueError, match="original error"):
        failing()


def test_export_runs_in_background_and_drain_is_bounded(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "test")
    monkeypatch.setenv("LANGSMITH_TRACE_LIMIT", "10")
    finished = threading.Event()
    gate = threading.Event()
    def slow_export(span): gate.wait(2); finished.set()
    monkeypatch.setattr(t, "_export", slow_export)
    @t.traced("test")
    def task(): return 42
    start = time.monotonic()
    try:
        assert task() == 42
        t.flush(.02)
        assert time.monotonic()-start < 1
    finally:
        gate.set()
        t.flush(3)
    assert finished.is_set()
