from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Target(Contract):
    by: Literal["role", "label", "text"]
    name: str = Field(min_length=1)
    role: Literal["button", "link", "textbox", "heading", "alert"] = "textbox"


class Action(Contract):
    kind: Literal["click", "fill", "read", "check"]
    target: Target
    input_key: str | None = None
    output_key: str | None = None
    reason: str = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def binding(self):
        if self.kind == "fill" and not self.input_key:
            raise ValueError("fill requires an input reference")
        if self.kind == "read" and not self.output_key:
            raise ValueError("read requires an output reference")
        if self.kind != "fill" and self.input_key:
            raise ValueError("input binding only belongs on fill")
        if self.kind != "read" and self.output_key:
            raise ValueError("output binding only belongs on read")
        return self


class Parameter(Contract):
    type: Literal["string"] = "string"
    sensitive: bool = False
    pattern: str | None = None
    equals_input: str | None = None


class WorkflowSpec(Contract):
    name: str
    description: str
    inputs: dict[str, Parameter]
    outputs: dict[str, Parameter]
    success: Target


class Capability(WorkflowSpec):
    schema_version: Literal[1] = 1
    version: int = Field(ge=1)
    app: str
    app_version: str
    steps: list[Action] = Field(min_length=1)
    discovery_run: str
    source: Literal["llm", "human"] = "llm"
    recording_actor: Literal["human", "automated_demo"] = "human"

    @model_validator(mode="after")
    def references(self):
        for action in self.steps:
            if action.input_key and action.input_key not in self.inputs:
                raise ValueError("Unknown input reference")
            if action.output_key and action.output_key not in self.outputs:
                raise ValueError("Unknown output reference")
        if {a.output_key for a in self.steps if a.kind == "read"} != set(self.outputs):
            raise ValueError("Every output must have an extraction action")
        return self


class Decision(Contract):
    status: Literal["act", "done", "intervene"]
    action: Action | None = None
    reason: str = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def action_present(self):
        if (self.status == "act") != (self.action is not None):
            raise ValueError("Only act decisions must contain an action")
        return self


class Result(Contract):
    status: Literal["success", "business_outcome", "failure"]
    run_id: str
    code: str
    outputs: dict[str, str] = Field(default_factory=dict)
    step: int = 0
    expected: str = ""
    observed: str = ""
    human_assisted: bool = False


class Condition(Contract):
    text: str
    category: Literal["business", "recover", "intervene", "failure"]
    recovery: Action | None = None


class Profile(Contract):
    app: str
    version: str
    origins: list[str]
    routes: list[str]
    allowed_actions: list[str]
    risky_targets: list[str]
    automated_post_routes: list[str]
    risky_post_routes: list[str] = Field(default_factory=list)
    conditions: list[Condition] = Field(default_factory=list)
