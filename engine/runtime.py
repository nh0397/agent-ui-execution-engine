import json
import re
import threading
import time
import uuid
from pathlib import Path

from engine.contracts import Result, Target
from engine.safety import Evidence, Policy, PolicyError
from engine.surface import BrowserSurface


def validate_values(parameters, values):
    if set(parameters) != set(values):
        raise ValueError("Input/output fields do not match the contract")
    for key, parameter in parameters.items():
        value = values[key]
        if not isinstance(value, str) or not value:
            raise ValueError(f"{key} must be a nonempty string")
        if parameter.pattern and not re.fullmatch(parameter.pattern, value):
            raise ValueError(f"{key} does not match its declared pattern")


class BusinessOutcome(Exception):
    pass


class Runtime:
    def __init__(self, spec, inputs, profile, entry, directory, headed=False, approve_writes=False, operator_port=None):
        validate_values(spec.inputs, inputs)
        self.spec, self.inputs, self.profile = spec, inputs, profile
        self.run_id = str(uuid.uuid4())
        self.evidence = Evidence(Path(directory) / self.run_id, [inputs[k] for k, p in spec.inputs.items() if p.sensitive])
        self.outputs = {}
        self.step = 0
        self.human_assisted = False
        self.headed, self.approve_writes = headed, approve_writes
        self.operator_port = operator_port
        self.surface = BrowserSurface(Policy(profile), self.evidence, headed)
        self.start = time.monotonic()
        self.evidence.event("run_started", run_id=self.run_id, session_id=self.surface.session_id, capability=spec.name, write_approval=approve_writes)
        try:
            self.surface.open(entry)
            observation = self.surface.observe()
            if observation["app"] != profile.app or observation["app_version"] != profile.version:
                raise PolicyError("Application compatibility check failed")
        except Exception as exc:
            self.evidence.event("startup_failed", reason=type(exc).__name__)
            try:
                self.surface.snapshot()
            except Exception:
                pass
            self.surface.close()
            raise

    def intervene(self, reason, expected=None):
        self.evidence.event("intervention_requested", step=self.step, reason=reason, expected=expected, state=self.surface.observe())
        if not self.headed and self.operator_port is None:
            raise PolicyError("Human intervention requires a headed run")
        self.surface.owner = "human"
        self.human_assisted = True
        self.evidence.event("ownership", owner="human", session_id=self.surface.session_id)
        print(f"\nHuman control: {reason}. Expected before resume: {expected or 'safe state'}.\nOperate this browser, then type resume or abort here.")
        answer = []
        bridge = None
        if self.operator_port is not None:
            from engine.operator import OperatorBridge
            bridge = OperatorBridge(self.operator_port)
            print(f"Live operator view: http://127.0.0.1:{self.operator_port}", flush=True)
        def read_answer():
            try:
                answer.append(input().strip())
            except EOFError:
                answer.append("abort")
        if bridge is None:
            threading.Thread(target=read_answer, daemon=True).start()
        until = time.monotonic() + 300
        try:
            while not answer and time.monotonic() < until:
                # All browser access remains on its owning thread. HTTP handlers only enqueue commands.
                self.surface.page.wait_for_timeout(100)
                if bridge is not None:
                    bridge.frame = self.surface.page.screenshot()
                    while not bridge.commands.empty():
                        command = bridge.commands.get_nowait()
                        kind = command["kind"]
                        self.evidence.event("operator_command", kind=kind, session_id=self.surface.session_id)
                        if kind in ("resume", "abort"):
                            answer.append(kind)
                            break
                        if kind == "click":
                            x, y = float(command["x"]), float(command["y"])
                            viewport = self.surface.page.viewport_size
                            if not (0 <= x < viewport["width"] and 0 <= y < viewport["height"]):
                                raise PolicyError("Operator click outside viewport")
                            self.surface.page.mouse.click(x, y)
                        elif kind == "type":
                            self.surface.page.keyboard.insert_text(str(command["text"])[:1000])
                        elif kind == "key" and command.get("key") in ("Tab", "Enter", "Escape", "Backspace"):
                            self.surface.page.keyboard.press(command["key"])
                        elif kind == "scroll":
                            self.surface.page.mouse.wheel(0, max(-1000, min(1000, int(command["delta"]))))
        finally:
            if bridge is not None:
                bridge.close()
        if not answer or answer[0] != "resume":
            raise PolicyError("Intervention aborted or expired")
        self.surface.assert_policy()
        if expected and not self.surface.visible(Target.model_validate(expected)):
            raise PolicyError("Resume checkpoint not satisfied")
        self.surface.owner = "automation"
        self.evidence.event("ownership", owner="automation", session_id=self.surface.session_id, state=self.surface.observe())

    def conditions(self, expected=None):
        for attempt in range(3):
            # Exact alert targeting avoids accidental matches in help text or other controls.
            condition = next((c for c in self.profile.conditions if self.surface.has_alert(c.text)), None)
            if not condition:
                return
            self.evidence.event("condition", category=condition.category, code=condition.text, attempt=attempt)
            if condition.category == "business":
                raise BusinessOutcome(condition.text)
            if condition.category == "failure":
                raise PolicyError(condition.text)
            if condition.category == "intervene":
                self.intervene(condition.text, expected)
            elif condition.recovery and attempt < 2:
                self.surface.write_authorized = False
                self.surface.execute(condition.recovery, self.inputs)
            else:
                raise PolicyError("Recovery budget exhausted")
        raise PolicyError("Recovery budget exhausted")

    def act(self, action):
        if time.monotonic() - self.start > 900:
            raise PolicyError("Run deadline exceeded")
        risky = action.target.name in self.profile.risky_targets
        if risky and not self.approve_writes:
            # Human performs the risky action; it is not silently authorized by resume.
            self.intervene("Perform or decline the requested risky action", self.spec.success.model_dump())
            return
        self.surface.write_authorized = action.kind == "click"
        self.surface.risky_authorized = risky and self.approve_writes
        self.evidence.event("action", step=self.step, action=action.model_dump())
        value = self.surface.execute(action, self.inputs)
        self.surface.write_authorized = False
        if action.output_key:
            if action.output_key not in self.spec.outputs:
                raise PolicyError("Undeclared output")
            parameter = self.spec.outputs[action.output_key]
            validate_values({action.output_key: parameter}, {action.output_key: value})
            if parameter.equals_input and value != self.inputs[parameter.equals_input]:
                raise PolicyError("Extracted output does not match its declared input")
            self.outputs[action.output_key] = value
        self.step += 1

    def finish(self):
        if not self.surface.visible(self.spec.success):
            raise PolicyError("Success checkpoint not reached")
        validate_values(self.spec.outputs, self.outputs)
        for key, parameter in self.spec.outputs.items():
            if parameter.equals_input and self.outputs[key] != self.inputs[parameter.equals_input]:
                raise PolicyError("Saved output does not match requested input")
        return Result(status="success", code="completed", run_id=self.run_id, outputs=self.outputs, step=self.step, human_assisted=self.human_assisted)

    def result(self, exc):
        code = str(exc) if isinstance(exc, (PolicyError, BusinessOutcome, ValueError)) else type(exc).__name__
        try:
            self.surface.snapshot()
        except Exception:
            self.evidence.save("failure-snapshot.json", {"state": "unavailable", "reason": code})
        return Result(status="business_outcome" if isinstance(exc, BusinessOutcome) else "failure", code=code, run_id=self.run_id, step=self.step, expected="Declared action and workflow checkpoints", observed=self.evidence.clean(str(exc))[:1500], human_assisted=self.human_assisted)

    def close(self, result):
        persisted = result.model_dump()
        for key, parameter in self.spec.outputs.items():
            if parameter.sensitive and key in persisted["outputs"]:
                persisted["outputs"][key] = "[REDACTED]"
        self.evidence.save("result.json", persisted)
        self.evidence.event("run_finished", result=persisted)
        self.surface.close()


def replay(capability, inputs, profile, entry, directory, **options):
    if capability.app != profile.app or capability.app_version != profile.version:
        raise ValueError("Capability application version mismatch")
    runtime = Runtime(capability, inputs, profile, entry, directory, **options)
    runtime.evidence.event("mode", mode="replay", capability_version=capability.version, discovery_run=capability.discovery_run)
    try:
        for action in capability.steps:
            runtime.conditions(action.target.model_dump())
            runtime.act(action)
        runtime.conditions()
        result = runtime.finish()
    except Exception as exc:
        result = runtime.result(exc)
    finally:
        runtime.close(result)
    return result
