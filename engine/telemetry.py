"""Optional metadata-only LangSmith export. No model dependency or raw argument capture.

Complete traces enter a bounded background queue. Export failures never change a
workflow result. A reservation counts against the local cap even if export fails.
"""
import contextlib
import contextvars
import datetime as dt
import functools
import inspect
import os
import queue
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from engine.settings import ROOT, load_env

ENV_KEYS = {"LANGSMITH_TRACING", "LANGSMITH_API_KEY", "LANGSMITH_PROJECT",
            "LANGSMITH_ENDPOINT", "LANGSMITH_TRACE_LIMIT", "LANGSMITH_USAGE_DB"}
ENDPOINTS = {"https://api.smith.langchain.com", "https://eu.api.smith.langchain.com"}
MAX_SPANS = 160
MAX_EVENTS = 160
_current = contextvars.ContextVar("trace_span", default=None)
_context = contextvars.ContextVar("trace_context", default={})
_queue = queue.Queue(maxsize=16)
_worker_lock = threading.Lock()
_worker = None


def config():
    load_env(ENV_KEYS)
    limit = int(os.getenv("LANGSMITH_TRACE_LIMIT", "1000"))
    return {"enabled": os.getenv("LANGSMITH_TRACING", "false").lower() == "true",
            "key": os.getenv("LANGSMITH_API_KEY", ""),
            "project": os.getenv("LANGSMITH_PROJECT", "agent-ui-execution-engine"),
            "endpoint": os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com").rstrip("/"),
            "limit": max(0, min(limit, 5000)),
            "database": Path(os.getenv("LANGSMITH_USAGE_DB", str(ROOT / "work/langsmith-usage.sqlite3")))}


@contextlib.contextmanager
def connect(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=.2)
    try:
        db.execute("CREATE TABLE IF NOT EXISTS traces (id TEXT PRIMARY KEY, month TEXT, state TEXT, url TEXT, error TEXT)")
        with db:
            yield db
    finally:
        db.close()


def month():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m")


def update(configured, trace_id, state, url=None, error=None):
    try:
        with connect(configured["database"]) as db:
            db.execute("UPDATE traces SET state=?,url=?,error=? WHERE id=?", (state, url, error, trace_id))
    except Exception:
        pass


def status():
    try:
        cfg = config()
        count, last = 0, None
        if cfg["database"].exists():
            with connect(cfg["database"]) as db:
                count = db.execute("SELECT count(*) FROM traces WHERE month=?", (month(),)).fetchone()[0]
                row = db.execute("SELECT state,error FROM traces ORDER BY rowid DESC LIMIT 1").fetchone()
                last = {"state": row[0], "error": row[1]} if row else None
        return {"enabled": cfg["enabled"], "configured": bool(cfg["key"]),
                "endpoint_allowed": cfg["endpoint"] in ENDPOINTS,
                "traces_this_month": count, "monthly_limit": cfg["limit"], "last_export": last}
    except Exception:
        return {"enabled": False, "configured": False, "error": "Tracing configuration unavailable"}


def lookup(trace_id):
    try:
        with connect(config()["database"]) as db:
            row = db.execute("SELECT state,url,error FROM traces WHERE id=?", (str(trace_id),)).fetchone()
        return {"id": trace_id, "state": row[0], "url": row[1], "error": row[2]} if row else None
    except Exception:
        return None


def uuid_text(value):
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


@contextlib.contextmanager
def bind_context(**values):
    safe = {k: uuid_text(v) for k, v in values.items() if k in {"job_id", "conversation_id"}}
    if callable(values.get("on_start")):
        safe["on_start"] = values["on_start"]
    token = _context.set({**_context.get(), **safe})
    try:
        yield
    finally:
        _context.reset(token)


def safe_summary(value):
    """An allowlist, not a general-purpose PII scrubber. Never traverse arbitrary strings."""
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    if not isinstance(value, dict):
        return {}
    out = {}
    enums = {"status": {"success", "business_outcome", "failure"},
             "mode": {"discovery", "replay", "recording"},
             "owner": {"human", "automation", "none"},
             "category": {"business", "recover", "intervene", "failure"},
             "kind": {"click", "fill", "read", "check", "type", "key", "scroll", "resume", "abort", "finish", "request_control", "stop_recording", "continue_recording"},
             "intent": {"discover", "use_workflow"},
             "choice": {"learn", "record", "details", "confirmation", "unclear"}}
    for key, allowed in enums.items():
        if isinstance(value.get(key), str) and value[key] in allowed:
            out[key] = value[key]
    for key in ("step", "attempt", "prompt_eval_count", "eval_count", "capability_version"):
        if type(value.get(key)) is int and value[key] >= 0:
            out[key] = value[key]
    for key in ("human_assisted", "supported", "model_used", "write_approval"):
        if type(value.get(key)) is bool:
            out[key] = value[key]
    for key in ("run_id", "session_id"):
        if uuid_text(value.get(key)):
            out[key] = uuid_text(value[key])
    for key in ("matches", "values", "outputs"):
        if isinstance(value.get(key), (list, dict)):
            out[key + "_count"] = len(value[key])
    return out


class Span:
    def __init__(self, name, kind, parent, cfg):
        self.cfg = cfg
        self.operation = name
        self.parent = parent
        self.root = parent.root if parent else self
        self.id = str(uuid.uuid4())
        self.start = dt.datetime.now(dt.timezone.utc)
        order = self.start.strftime("%Y%m%dT%H%M%S%fZ") + self.id
        self.order = parent.order + "." + order if parent else order
        self.record = {"id": self.id, "name": name, "run_type": kind, "inputs": {},
                       "start_time": self.start, "trace_id": self.root.id,
                       "dotted_order": self.order, "session_name": cfg["project"],
                       "extra": {"metadata": {}}, "events": [], "outputs": {}}
        readable = {'chat.match':'Find a saved workflow', 'chat.extract_inputs':'Read the requested workflow inputs',
                    'chat.setup':'Understand the workflow setup choice', 'chat.prepare_discovery':'Prepare a new workflow request'}
        if name in readable:
            self.record['name'] = readable[name]
            self.record['extra']['metadata']['operation'] = name
        if parent:
            self.record["parent_run_id"] = parent.id
        else:
            self.spans = []
            self.calls = 0
            self.dropped = 0
        self.root.spans.append(self.record)

    def finish(self, result=None, error=None):
        # Instrumentation must never replace a result or hide the original error.
        with contextlib.suppress(Exception):
            self._finish(result, error)

    def _finish(self, result=None, error=None):
        self.record["end_time"] = dt.datetime.now(dt.timezone.utc)
        self.record["outputs"].update(safe_summary(result))
        if self.record["run_type"] == "llm" and isinstance(result, dict):
            usage = {"input_tokens": result.get("prompt_eval_count"), "output_tokens": result.get("eval_count")}
            if all(type(v) is int and v >= 0 for v in usage.values()):
                usage["total_tokens"] = sum(usage.values())
                self.record["outputs"]["usage_metadata"] = usage
        if error or self.record["outputs"].get("status") == "failure":
            self.record.setdefault("error", "Operation failed; inspect local evidence for details")
        if self is self.root:
            self.record["outputs"].update(model_calls=self.calls, omitted_spans=self.dropped)


@contextlib.contextmanager
def operation(name, kind="chain"):
    parent = _current.get()
    span, token = None, None
    try:
        cfg = parent.cfg if parent else config()
        if parent and len(parent.root.spans) >= MAX_SPANS:
            parent.root.dropped += 1
        elif cfg["enabled"] and cfg["key"] and cfg["endpoint"] in ENDPOINTS:
            span = Span(name, kind, parent, cfg)
            if parent is None:
                with connect(cfg["database"]) as db:
                    db.execute("BEGIN IMMEDIATE")
                    used = db.execute("SELECT count(*) FROM traces WHERE month=?", (month(),)).fetchone()[0]
                    if used >= cfg["limit"]:
                        span = None
                    else:
                        db.execute("INSERT INTO traces VALUES(?,?,'collecting',NULL,NULL)", (span.id, month()))
                if span:
                    metadata = {k: v for k, v in _context.get().items() if k in {"job_id", "conversation_id"} and v}
                    # LangSmith groups requests with the same session_id into a conversation.
                    if metadata.get("conversation_id"):
                        metadata["session_id"] = metadata["conversation_id"]
                    span.record["extra"]["metadata"].update(metadata)
                    callback = _context.get().get("on_start")
                    if callback:
                        callback(span.id)
            if span:
                token = _current.set(span)
    except Exception:
        span = None
    try:
        yield span
    except BaseException:
        if span:
            span.finish(error=not getattr(span, 'expected_outcome', False))
        raise
    finally:
        if token is not None:
            _current.reset(token)
        if span:
            span.record.setdefault("end_time", dt.datetime.now(dt.timezone.utc))
            if span is span.root:
                span.finish()
                with contextlib.suppress(Exception):
                    _submit(span)


def traced(name, kind="chain"):
    def decorate(fn):
        if inspect.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def async_call(*args, **kwargs):
                with operation(name, kind) as span:
                    result = await fn(*args, **kwargs)
                    if span:
                        span.finish(result)
                    return result
            return async_call
        @functools.wraps(fn)
        def call(*args, **kwargs):
            with operation(name, kind) as span:
                result = fn(*args, **kwargs)
                if span:
                    span.finish(result)
                return result
        return call
    return decorate


def model_sent(provider, model):
    span = _current.get()
    if span:
        with contextlib.suppress(Exception):
            span.root.calls += 1
            # Provider/model are deployment settings, never message content or credentials.
            span.record["extra"]["metadata"].update(ls_provider=provider, ls_model_name=model)
            purpose = 'Choose the next UI action' if span.root.operation == 'workflow.discovery' else 'Understand the chat request'
            span.record['name'] = purpose
            span.record['outputs']['purpose'] = purpose
            span.record['outputs']['timing_note'] = 'Duration includes any pre-request pacing wait.'


def describe_workflow(title, profile):
    """Called with a reviewed title, never the raw natural-language request."""
    span = _current.get()
    if span:
        with contextlib.suppress(Exception):
            root = span.root
            root.profile = profile
            mode = {'workflow.discovery':'Discover', 'workflow.replay':'Replay', 'workflow.recording':'Record'}.get(root.operation, 'Run')
            root.record['name'] = f'{mode}: {title}'
            root.record['extra']['metadata']['operation'] = root.operation
            root.record['outputs']['task'] = title


def describe_result(explanation):
    span = _current.get()
    if span:
        with contextlib.suppress(Exception):
            # This object comes from the deterministic reviewed-vocabulary renderer.
            span.root.record['outputs'].update({k:v for k,v in explanation.items() if k != 'timeline'})
            if explanation['status'] == 'failure':
                span.root.record['error'] = explanation['summary']


def event(name, data):
    span = _current.get()
    if not span or len(span.record["events"]) >= MAX_EVENTS:
        return
    allowed = {"run_started", "mode", "observation", "model_decision", "action", "condition", "recovery_action", "intervention_requested", "ownership", "operator_command", "human_step", "human_action", "run_finished", "model_capacity_wait", "recording_review", "recording_resumed"}
    if name not in allowed:
        return
    summary = safe_summary(data)
    profile = getattr(span.root, 'profile', None)
    if profile and name == 'condition':
        from engine.observability import error_info
        summary.update(error_info(data.get('code'), profile))
    if profile and name == 'model_decision':
        from engine.observability import action_info
        chosen = (data.get('decision') or {}).get('action')
        if chosen:
            summary.update(action_info(chosen, profile))
            summary['purpose'] = 'The model selected this allowed action from the current UI.'
            model_span = next((s for s in reversed(span.root.spans) if s['run_type'] == 'llm'), None)
            if model_span:
                model_span['outputs']['selected_action'] = summary['title']
        else:
            summary['purpose'] = 'Discovery requested human help or reached its completion check.'
    if isinstance(data.get("action"), dict):
        summary.update(safe_summary(data["action"]))
        if profile and name in {'action', 'recovery_action', 'human_step'}:
            from engine.observability import action_info
            summary.update(action_info(data['action'], profile))
    if name == "model_decision":
        summary.update(safe_summary((data.get("decision") or {}).get("action") or {}))
    if name == "observation":
        summary["control_count"] = len((data.get("state") or {}).get("controls", []))
    span.record["events"].append({"name": name, "time": dt.datetime.now(dt.timezone.utc).isoformat(), "kwargs": summary})


def _make_client(cfg, on_error=None):
    from langsmith import Client
    import requests
    from urllib3.util.retry import Retry
    session = requests.Session()
    session.trust_env = False
    return Client(api_url=cfg["endpoint"], api_key=cfg["key"], session=session,
                  auto_batch_tracing=False, timeout_ms=2000, retry_config=Retry(total=0),
                  omit_traced_runtime_info=True, hide_inputs=True, tracing_sampling_rate=1,
                  tracing_error_callback=on_error)


def _confirm(client, cfg, trace_id):
    # Ingestion is eventually consistent. Only this background worker waits.
    for attempt in range(6):
        try:
            run = client.read_run(trace_id)
            url = client.get_run_url(run=run)
            if url.startswith(("https://smith.langchain.com/", "https://eu.smith.langchain.com/")):
                update(cfg, trace_id, "exported", url=url)
                return
        except Exception:
            pass
        if attempt < 5:
            time.sleep(.5 * 2**attempt)


def _export(span):
    client = None
    try:
        failures = []
        # The SDK reports some ingestion failures through this callback instead of raising.
        client = _make_client(span.cfg, lambda _: failures.append(True))
        client.batch_ingest_runs(create=span.spans)
        if failures:
            raise RuntimeError("Trace export unavailable")
        update(span.cfg, span.id, "unconfirmed", error="Waiting for trace confirmation")
        # A link is marked available only after the service can read the run.
        _confirm(client, span.cfg, span.id)
    except Exception:
        update(span.cfg, span.id, "failed", error="Trace export unavailable")
    finally:
        if client is not None:
            with contextlib.suppress(Exception):
                client.close()


def _drain():
    while True:
        span = _queue.get()
        try:
            _export(span)
        except Exception:
            update(span.cfg, span.id, "failed", error="Trace export unavailable")
        finally:
            _queue.task_done()


def _submit(span):
    global _worker
    try:
        update(span.cfg, span.id, "queued")
        with _worker_lock:
            if _worker is None or not _worker.is_alive():
                _worker = threading.Thread(target=_drain, name="langsmith-export", daemon=True)
                _worker.start()
        _queue.put_nowait(span)
    except queue.Full:
        update(span.cfg, span.id, "dropped", error="Trace queue full")
    except Exception:
        update(span.cfg, span.id, "failed", error="Trace export unavailable")


def flush(timeout=8):
    """Bounded best-effort drain for short-lived CLI processes."""
    until = time.monotonic() + timeout
    while _queue.unfinished_tasks and time.monotonic() < until:
        time.sleep(.05)
