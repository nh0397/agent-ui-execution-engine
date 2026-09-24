import pytest


@pytest.fixture(autouse=True)
def private_tracing_off(monkeypatch, tmp_path):
    """No test may export through a developer's private .env by accident."""
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGSMITH_USAGE_DB", str(tmp_path / "trace-usage.sqlite3"))


@pytest.fixture
def trace_capture(monkeypatch):
    """Exercise real instrumentation without a network exporter."""
    from engine import telemetry
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-private-key")
    monkeypatch.setenv("LANGSMITH_TRACE_LIMIT", "100")
    monkeypatch.setenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")
    spans = []
    monkeypatch.setattr(telemetry, "_submit", spans.append)
    return spans
