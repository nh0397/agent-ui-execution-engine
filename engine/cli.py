import argparse
import json
import os
from pathlib import Path

from engine.contracts import Capability, Profile, WorkflowSpec


def main():
    parser = argparse.ArgumentParser(description="Discover and replay UI capabilities")
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo")
    demo.add_argument("--port", type=int, default=8000)
    demo.add_argument("--scenario", default="normal")
    demo.add_argument("--database", default="work/customers.sqlite3")
    for command in ("discover", "replay"):
        p = sub.add_parser(command)
        p.add_argument("--profile", default="config/customer-service.json")
        p.add_argument("--inputs", required=True)
        p.add_argument("--entry", default="http://127.0.0.1:8000")
        p.add_argument("--runs", default="runs")
        p.add_argument("--headed", action="store_true")
        p.add_argument("--operator-port", type=int, help="Expose a loopback operator view during handoff")
        p.add_argument("--approve-writes", action="store_true", help="Explicitly authorize configured risky UI actions for this invocation")
        p.add_argument("--capability", required=True)
        if command == "discover":
            p.add_argument("--spec", default="config/address-workflow.json")
            p.add_argument("--model", required=True)
            p.add_argument("--goal", required=True)
    args = parser.parse_args()
    if args.command == "demo":
        import uvicorn
        from demo.app import create_app
        uvicorn.run(create_app(args.database, args.scenario), host="127.0.0.1", port=args.port, access_log=False)
        return
    if Path(".browsers").exists():
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(Path(".browsers").resolve()))
    profile = Profile.model_validate_json(Path(args.profile).read_text(encoding="utf-8"))
    inputs = json.loads(Path(args.inputs).read_text(encoding="utf-8"))
    options = dict(inputs=inputs, profile=profile, entry=args.entry, directory=args.runs, headed=args.headed, approve_writes=args.approve_writes, operator_port=args.operator_port)
    if args.command == "discover":
        from engine.discovery import discover
        result = discover(WorkflowSpec.model_validate_json(Path(args.spec).read_text(encoding="utf-8")), model=args.model, goal=args.goal, capability_path=args.capability, **options)
    else:
        from engine.runtime import replay
        result = replay(Capability.model_validate_json(Path(args.capability).read_text(encoding="utf-8")), **options)
    # Declared sensitive outputs are returned by the Python API, but not echoed to terminal logs.
    print(json.dumps({"status": result.status, "code": result.code, "run_id": result.run_id, "step": result.step}, indent=2))
    from engine.telemetry import flush
    flush()
    raise SystemExit(1 if result.status == "failure" else 0)


if __name__ == "__main__":
    main()
