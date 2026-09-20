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
    def __init__(self, spec, inputs, profile, entry, directory, headed=False, approve_writes=False, operator_port=None, control=None, surface_factory=BrowserSurface):
        validate_values(spec.inputs, inputs)
        self.spec, self.inputs, self.profile = spec, inputs, profile
        self.run_id = str(uuid.uuid4())
        self.evidence = Evidence(Path(directory) / self.run_id, [inputs[k] for k, p in spec.inputs.items() if p.sensitive])
        self.outputs = {}
        self.step = 0
        self.expected = "Application entry and compatibility"
        self.human_assisted = False
        self.journal = None
        self.requested_takeover = False
        self.headed, self.approve_writes = headed, approve_writes
        self.operator_port = operator_port
        self.control = control
        self.surface = surface_factory(Policy(profile), self.evidence, headed)
        self.start = time.monotonic()
        self.evidence.event("run_started", run_id=self.run_id, session_id=self.surface.session_id, capability=spec.name, write_approval=approve_writes)
        try:
            self.surface.open(entry)
            observation = self.surface.observe()
            if observation["app"] != profile.app or observation["app_version"] != profile.version:
                raise PolicyError("Application compatibility check failed")
            self.publish()
        except Exception as exc:
            self.evidence.event("startup_failed", reason=type(exc).__name__)
            try:
                self.surface.snapshot()
            except Exception:
                pass
            self.surface.close()
            raise

    def publish(self):
        if self.control is not None:
            self.control.state = {"owner": self.surface.owner, "step": self.step, "session_id": self.surface.session_id}
            self.control.frame = self.surface.frame()

    def check_takeover(self, expected=None):
        if self.control is not None and self.control.takeover.is_set():
            self.control.takeover.clear()
            self.requested_takeover = True
            self.intervene("Operator requested control; return to the displayed checkpoint before resuming", expected)
            return True
        return False

    def check_cancel(self):
        if self.control is not None and self.control.cancel.is_set():
            raise PolicyError("Run cancelled by operator")

    def intervene(self, reason, expected=None):
        self.evidence.event("intervention_requested", step=self.step, reason=reason, expected=expected, state=self.surface.observe())
        if not self.headed and self.operator_port is None and self.control is None:
            raise PolicyError("Human intervention requires a headed run")
        self.surface.owner = "human"
        self.human_assisted = True
        self.evidence.event("ownership", owner="human", session_id=self.surface.session_id)
        print(f"\nHuman control: {reason}. Expected before resume: {expected or 'safe state'}.\nOperate this browser, then type resume or abort here.")
        answer = []
        bridge = self.control
        if self.control is not None:
            self.control.intervention = {"reason": reason, "expected": expected, "capability": self.spec.name}
            self.publish()
        if bridge is None and self.operator_port is not None:
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
                self.check_cancel()
                # All browser access remains on its owning thread. HTTP handlers only enqueue commands.
                self.surface.pump_events()
                if bridge is not None:
                    bridge.frame = self.surface.frame()
                    while not bridge.commands.empty():
                        command = bridge.commands.get_nowait()
                        kind = command["kind"]
                        self.evidence.event("operator_command", kind=kind, operator_id=command.get("operator_id"), session_id=self.surface.session_id)
                        if kind in ("resume", "abort"):
                            answer.append(kind)
                            break
                        from engine.recording import CaptureJournal
                        if self.journal is None:
                            self.journal = CaptureJournal(self.surface, self.evidence)
                        if kind == "type" and command.get("text"):
                            self.evidence.secrets.append(command["text"])
                        before = self.journal.capture("before")
                        self.surface.operator_action(command)
                        after = self.journal.capture("after")
                        self.journal.append(command, before, after)
        finally:
            if bridge is not None and self.control is None:
                bridge.close()
        if not answer or answer[0] != "resume":
            raise PolicyError("Intervention aborted or expired")
        self.surface.assert_policy()
        resumed = self.surface.observe()
        if resumed["app"] != self.profile.app or resumed["app_version"] != self.profile.version:
            raise PolicyError("Resume application compatibility check failed")
        if expected and not self.surface.visible(Target.model_validate(expected)):
            raise PolicyError("Resume checkpoint not satisfied")
        # Commands queued for this ownership interval cannot spill into the next one.
        if self.control is not None:
            while not self.control.commands.empty():
                self.control.commands.get_nowait()
        self.surface.owner = "automation"
        if self.control is not None:
            self.control.intervention = None
            self.publish()
        self.evidence.event("ownership", owner="automation", session_id=self.surface.session_id, state=self.surface.observe())

    def conditions(self, expected=None):
        self.check_cancel()
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
                self.evidence.event("recovery_action", action=condition.recovery.model_dump(), attempt=attempt)
                self.surface.execute(condition.recovery, self.inputs)
                self.publish()
            else:
                raise PolicyError("Recovery budget exhausted")
        raise PolicyError("Recovery budget exhausted")

    def act(self, action):
        self.check_cancel()
        self.check_takeover(action.target.model_dump())
        self.expected = f"{action.kind}: {action.target.name}"
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
        self.publish()

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
        return Result(status="business_outcome" if isinstance(exc, BusinessOutcome) else "failure", code=self.evidence.clean(code), run_id=self.run_id, step=self.step, expected=self.expected, observed=self.evidence.clean(str(exc) if isinstance(exc, (PolicyError, BusinessOutcome, ValueError)) else type(exc).__name__)[:1500], human_assisted=self.human_assisted)

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
