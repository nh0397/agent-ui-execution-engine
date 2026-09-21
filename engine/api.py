"""Local dashboard API. Browser work stays on one dedicated owning thread per run."""
import json
import os
import queue
import re
import io
import zipfile
import secrets
import threading
import time
import uuid
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from engine.contracts import Capability, Profile, WorkflowSpec
from engine.runtime import replay, validate_values

ROOT = Path(__file__).resolve().parents[1]
PROFILES = [
    {"id": "mira", "name": "Mira Chen", "role": "Operator"},
    {"id": "sam", "name": "Sam Rivera", "role": "Operator"},
    {"id": "taylor", "name": "Taylor Morgan", "role": "Viewer"},
]
SCENARIOS = ("normal", "slow", "transient", "session-expired", "permission-denied", "uncertain-save")


class Invocation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["discovery", "replay", "recording"]
    goal: str = Field(default="", max_length=2000)
    inputs: dict[str, str] = Field(default_factory=dict)
    name: str = Field(default="Recorded workflow", min_length=1, max_length=80)
    capability_id: str = "example"
    approve_writes: bool = False
    scenario: Literal["normal", "slow", "transient", "session-expired", "permission-denied", "uncertain-save"] = "normal"
    model: Literal["mistral:latest", "llama3.1:latest"] = "mistral:latest"


class OperatorCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["click", "type", "key", "scroll", "resume", "abort", "request_control", "finish"]
    x: float = Field(default=0, ge=0, le=4096, allow_inf_nan=False)
    y: float = Field(default=0, ge=0, le=4096, allow_inf_nan=False)
    text: str = Field(default="", max_length=1000)
    key: Literal["Tab", "Enter", "Escape", "Backspace"] = "Tab"
    parameter_key: str = Field(default="", max_length=50)
    success_name: str = Field(default="", max_length=150)
    output_bindings: dict[str, str] = Field(default_factory=dict)
    delta: int = Field(default=0, ge=-1000, le=1000)


class LiveControl:
    def __init__(self):
        self.commands = queue.Queue(maxsize=32)
        self.cancel = threading.Event()
        self.takeover = threading.Event()
        self.recording = {}
        self.frame = b""
        self.state = {"owner": "automation", "step": 0, "session_id": ""}
        self.intervention = None


class AgentMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=2000)
    model: Literal["mistral:latest", "llama3.1:latest"] = "mistral:latest"


class InputMessage(AgentMessage):
    capability_id: str


def create_app(root: Path | None = None):
    root = Path(root or ROOT)
    if (root / ".browsers").exists():
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(root / ".browsers"))
    storage = Path(os.getenv("DASHBOARD_STORAGE", str(root / "work/dashboard")))
    storage.mkdir(parents=True, exist_ok=True)
    runs_root = storage / "runs"
    runs_root.mkdir(exist_ok=True)
    artifacts = storage / "capabilities"
    artifacts.mkdir(exist_ok=True)
    drafts = storage / "drafts"
    drafts.mkdir(exist_ok=True)
    spec = WorkflowSpec.model_validate_json((root / "config/address-workflow.json").read_text())
    base_profile = Profile.model_validate_json((root / "config/customer-service.json").read_text())
    entry = os.getenv("DEMO_ENTRY", "http://127.0.0.1:8000").rstrip("/")
    profile = base_profile.model_copy(update={"origins": [entry]})
    origins = set(os.getenv("DASHBOARD_ORIGINS", "http://127.0.0.1:5174,http://127.0.0.1:5173,http://localhost:5173,http://localhost:5174,http://127.0.0.1:8001").split(","))
    app = FastAPI(title="Agent UI Execution API", docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
    sessions = {}
    jobs = {}
    controls = {}
    lock = threading.Lock()
    persistence_lock = threading.Lock()
    active = threading.Lock()
    video_lock = threading.Lock()
    for path in storage.glob("job-*.json"):
        job = json.loads(path.read_text())
        if job["status"] == "running":
            job.update(status="failure", code="Worker restarted; session cannot be resumed")
        jobs[job["id"]] = job

    def save(job):
        # Contains only status, IDs, and declared non-sensitive metadata. Never input values.
        with persistence_lock:
            temp = storage / f"job-{job['id']}.tmp"
            temp.write_text(json.dumps(job, indent=2), encoding="utf-8")
            temp.replace(storage / f"job-{job['id']}.json")

    @app.middleware("http")
    async def local_security(request, call_next):
        if request.url.hostname not in {"127.0.0.1", "localhost", "testserver", "worker"}:
            return JSONResponse({"detail": "Untrusted host"}, status_code=403)
        if request.method not in {"GET", "HEAD"} and request.headers.get("origin") not in origins:
            return JSONResponse({"detail": "Untrusted origin"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    def session(request, operator=False):
        value = sessions.get(request.cookies.get("workspace_session", ""))
        if not value or value["expires"] < time.time():
            raise HTTPException(401, "Choose a demo profile to open a session")
        if operator and value["profile"]["role"] != "Operator":
            raise HTTPException(403, "Viewer profiles cannot execute or control runs")
        if request.method != "GET" and not secrets.compare_digest(request.headers.get("x-csrf-token", ""), value["csrf"]):
            raise HTTPException(403, "Invalid session token")
        return value

    def catalog():
        # A reset workspace can hide the bundled example without deleting evidence.
        result = {} if (storage / ".hide-example").exists() else {"example": root / "capabilities/update-address.v1.json"}
        result.update({p.stem: p for p in artifacts.glob("*.json")})
        return result

    def read_events(job):
        folder = runs_root / job["id"]
        paths = list(folder.glob("*/events.jsonl"))
        if not paths:
            return []
        events = []
        for line in paths[0].read_text(encoding="utf-8").splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass  # A concurrently written final line is retried on the next poll.
        return events

    def public_job(job):
        value = dict(job)
        control = controls.get(job["id"])
        value["live"] = {**control.state, "intervention": control.intervention, "has_frame": bool(control.frame), "takeover_requested": control.takeover.is_set()} if control else None
        events = read_events(job)
        value["actions"] = sum(e["event"] == "action" or (e["event"] == "human_step" and bool(e.get("action"))) for e in events)
        value["model_decisions"] = sum(e["event"] == "model_decision" for e in events)
        value["events"] = events
        value["recording"] = control.recording if control else {}
        recording_files = list((runs_root / job["id"]).glob("*/recording.json"))
        if recording_files:
            try:
                value["recording"] = {**value["recording"], "steps": json.loads(recording_files[0].read_text())}
            except json.JSONDecodeError:
                pass
        draft = drafts / f"{job['id']}.json"
        value["draft"] = json.loads(draft.read_text()) if job["status"] == "success" and draft.exists() else None
        value["has_video"] = any((runs_root / job["id"]).glob("*/steps.webm"))
        result_paths = list((runs_root / job["id"]).glob("*/result.json"))
        if result_paths:
            try:
                value["result"] = json.loads(result_paths[0].read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        return value

    @app.get("/api/health")
    async def health():
        async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
            checks = {}
            for name, url in [("bank", entry + "/health"), ("model", os.getenv("OLLAMA_URL", "http://127.0.0.1:11434") + "/api/tags")]:
                try:
                    reply = await client.get(url)
                    checks[name] = reply.is_success
                    if name == "model" and reply.is_success:
                        checks["models"] = [m["name"] for m in reply.json().get("models", [])]
                except httpx.HTTPError:
                    checks[name] = False
        return {"status": "ready", "bank_url": os.getenv("DEMO_PUBLIC_URL", entry if "127.0.0.1" in entry or "localhost" in entry else "http://127.0.0.1:8000"), **checks}

    @app.post("/api/session")
    async def choose_session(request: Request, response: Response):
        data = await request.json()
        person = next((p for p in PROFILES if p["id"] == data.get("profile_id")), None)
        if not person:
            raise HTTPException(400, "Unknown demo profile")
        sid, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        sessions[sid] = {"profile": person, "csrf": csrf, "expires": time.time() + 28800}
        response.set_cookie("workspace_session", sid, httponly=True, samesite="strict", max_age=28800, path="/api")
        return {"profile": person, "csrf": csrf, "demo": True}

    @app.get("/api/workflow-spec")
    def workflow_spec(request: Request):
        session(request)
        return spec.model_dump()

    @app.get("/api/capabilities")
    def capabilities(request: Request):
        session(request)
        return [{"id": key, "capability": json.loads(path.read_text(encoding="utf-8"))} for key, path in catalog().items()]

    @app.get("/api/runs")
    def list_runs(request: Request):
        session(request)
        with lock:
            return [public_job(job) for job in sorted(jobs.values(), key=lambda j: j["created"], reverse=True)]

    def get_job(job_id):
        if job_id not in jobs:
            raise HTTPException(404, "Run not found")
        return jobs[job_id]

    @app.post("/api/agent/match")
    async def agent_match(body: AgentMessage, request: Request):
        session(request)
        if not body.message.strip():
            raise HTTPException(422, "Describe the task you want to perform")
        from engine.catalog_agent import match_capabilities
        saved = {key: Capability.model_validate_json(path.read_text(encoding="utf-8")) for key, path in catalog().items()}
        try:
            result = await match_capabilities(body.message.strip(), saved, body.model)
        except httpx.HTTPError:
            raise HTTPException(503, "The local model is unavailable or timed out. Start Ollama or choose a workflow directly in Capabilities.")
        except (ValueError, KeyError, TypeError):
            raise HTTPException(502, "The model could not return a valid catalog selection. Please try again.")
        return {**result, "catalog_count": len(saved)}

    @app.get("/api/runs/{job_id}")
    def run_detail(job_id: str, request: Request):
        session(request)
        return public_job(get_job(job_id))

    @app.post("/api/agent/inputs")
    async def agent_inputs(body: InputMessage, request: Request):
        session(request)
        path = catalog().get(body.capability_id)
        if path is None:
            raise HTTPException(404, "Saved workflow no longer exists")
        from engine.catalog_agent import extract_inputs
        try:
            values = await extract_inputs(body.message, Capability.model_validate_json(path.read_text(encoding="utf-8")), body.model)
        except httpx.HTTPError:
            raise HTTPException(503, "The local model could not read your request. Please try again.")
        except (ValueError, KeyError, TypeError):
            raise HTTPException(502, "I couldn't safely extract the inputs. Please describe the values again.")
        return {"values": values}

    @app.get("/api/runs/{job_id}/frame")
    def frame(job_id: str, request: Request):
        session(request)
        get_job(job_id)
        control = controls.get(job_id)
        if not control or not control.frame:
            return Response(status_code=204)
        return Response(control.frame, media_type="image/jpeg", headers={"Cache-Control":"no-store"})

    @app.post("/api/runs/{job_id}/control")
    def control_run(job_id: str, command: OperatorCommand, request: Request):
        operator = session(request, operator=True)["profile"]
        job = get_job(job_id)
        control = controls.get(job_id)
        if job["status"] != "running" or not control:
            raise HTTPException(409, "Run is not active")
        if command.kind == "request_control":
            if control.state["owner"] != "automation" or job["mode"] == "recording":
                raise HTTPException(409, "Control is already with the human")
            control.takeover.set()
            return {"accepted": True, "message": "Will pause at the next safe action boundary"}
        if command.kind == "finish" and job["mode"] != "recording":
            raise HTTPException(409, "Finish is only available while recording")
        if command.kind == "abort":
            control.cancel.set()
            job["code"] = "Cancellation requested; waiting for the current operation to stop"
            save(job)
            return {"accepted": True}
        if control.state["owner"] != "human":
            raise HTTPException(409, "The engine currently owns the session")
        try:
            control.commands.put_nowait({**command.model_dump(), "operator_id": operator["id"]})
        except queue.Full:
            raise HTTPException(429, "Wait for pending commands")
        return {"accepted": True}

    @app.post("/api/runs", status_code=202)
    def start_run(invocation: Invocation, request: Request):
        person = session(request, operator=True)["profile"]
        cap_path = catalog().get(invocation.capability_id)
        if invocation.mode == "replay" and cap_path is None:
            raise HTTPException(400, "Unknown capability")
        contract = Capability.model_validate_json(cap_path.read_text()) if invocation.mode == "replay" else spec
        try:
            if invocation.mode != "recording":
                validate_values(contract.inputs, invocation.inputs)
            if any(len(v) > 300 for v in invocation.inputs.values()):
                raise ValueError("Input exceeds 300 characters")
            if invocation.mode == "discovery" and not invocation.goal.strip():
                raise ValueError("Discovery needs a goal")
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        if not active.acquire(blocking=False):
            raise HTTPException(409, "Another run is active. Finish or cancel it first.")
        job_id = str(uuid.uuid4())
        job = {"id": job_id, "created": time.time(), "mode": invocation.mode, "status": "running", "code": "starting", "profile": person["name"], "capability_id": invocation.capability_id, "scenario": invocation.scenario, "approve_writes": invocation.approve_writes, "name": invocation.name if invocation.mode == "recording" else contract.name}
        control = LiveControl()
        with lock:
            jobs[job_id] = job
            controls[job_id] = control
        save(job)

        def execute():
            try:
                # This query sets a synthetic per-browser-session fault; no customer data API is used.
                options = dict(inputs=invocation.inputs, profile=profile, entry=entry + "/?scenario=" + invocation.scenario, directory=runs_root / job_id, approve_writes=invocation.approve_writes, control=control)
                if invocation.mode == "recording":
                    from engine.recording import record
                    result = record(name=invocation.name, description=invocation.goal or invocation.name,
                        draft_path=drafts / f"{job_id}.json", **options)
                elif invocation.mode == "discovery":
                    from engine.discovery import discover
                    result = discover(contract, model=invocation.model, goal=invocation.goal, capability_path=artifacts / f"{job_id}.json", **options)
                    if result.status == "success":
                        job["capability_id"] = job_id
                else:
                    result = replay(contract, **options)
                job.update(status=result.status, code=result.code, run_id=result.run_id)
            except Exception as exc:
                job.update(status="failure", code=type(exc).__name__)
            finally:
                control.state = {**control.state, "owner": "none"}
                control.intervention = None
                job["finished"] = time.time()
                try:
                    save(job)
                finally:
                    active.release()

        threading.Thread(target=execute, name=f"run-{job_id}", daemon=True).start()
        return {"id": job_id}

    @app.post("/api/runs/{job_id}/publish")
    def publish_recording(job_id: str, request: Request):
        session(request, operator=True)
        job = get_job(job_id)
        draft = drafts / f"{job_id}.json"
        if job["mode"] != "recording" or job["status"] != "success" or not draft.exists():
            raise HTTPException(409, "A verified recording draft is required")
        cap = Capability.model_validate_json(draft.read_text())
        destination = artifacts / f"{job_id}.json"
        if not destination.exists():
            with destination.open("x", encoding="utf-8") as f:
                f.write(cap.model_dump_json(indent=2))
        job["capability_id"] = job_id
        job["code"] = "Human recording published"
        save(job)
        return {"capability_id": job_id}

    @app.get("/api/runs/{job_id}/captures/{filename}")
    def capture(job_id: str, filename: str, request: Request):
        session(request)
        get_job(job_id)
        if not re.fullmatch(r"step-[0-9]{3}-(before|after)\.png", filename):
            raise HTTPException(404, "Capture not found")
        paths = list((runs_root / job_id).glob(f"*/{filename}"))
        if not paths:
            raise HTTPException(404, "Capture not found")
        return FileResponse(paths[0], media_type="image/png")

    @app.get("/api/runs/{job_id}/document")
    def document(job_id: str, request: Request):
        session(request)
        get_job(job_id)
        folders = list((runs_root / job_id).glob("*/WORKFLOW.md"))
        if not folders:
            raise HTTPException(404, "No documented human actions yet")
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in folders[0].parent.iterdir():
                if path.name in {"WORKFLOW.md", "recording.json", "draft.json"} or re.fullmatch(r"step-[0-9]{3}-(before|after)\.png", path.name):
                    archive.write(path, path.name)
        return Response(stream.getvalue(), media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="workflow-{job_id}.zip"'})

    @app.post("/api/runs/{job_id}/video")
    def build_video(job_id: str, request: Request):
        session(request)
        job = get_job(job_id)
        if job["status"] == "running":
            raise HTTPException(409, "Finish the recording before creating its video")
        folders = list((runs_root/job_id).glob('*/recording.json'))
        if not folders:
            raise HTTPException(404, "This run has no recorded step images")
        if not video_lock.acquire(blocking=False):
            raise HTTPException(409, "Another recording video is being prepared; try again shortly")
        try:
            from engine.video import make_step_video
            make_step_video(folders[0].parent, root)
        except (ValueError, OSError) as exc:
            raise HTTPException(422, str(exc) if isinstance(exc, ValueError) else 'Video encoder unavailable')
        finally:
            video_lock.release()
        return {"ready": True}

    @app.get("/api/runs/{job_id}/video")
    def video(job_id: str, request: Request):
        session(request)
        get_job(job_id)
        files = list((runs_root/job_id).glob('*/steps.webm'))
        if not files:
            raise HTTPException(404, "Recording video has not been prepared")
        return FileResponse(files[0], media_type='video/webm')

    @app.get("/api/runs/{job_id}/evidence")
    def export(job_id: str, request: Request):
        session(request)
        return public_job(get_job(job_id))

    dist = root / "frontend/dist"
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/")
        def index():
            return FileResponse(dist / "index.html")

    return app
