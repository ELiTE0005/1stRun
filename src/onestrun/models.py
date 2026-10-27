"""The shared data contracts. Every module builds against these. Change only through the lead."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    RECOVERING = "recovering"
    GAVE_UP = "gave_up"
    SKIPPED = "skipped"          # planner marked the step skipped_out_of_scope
    NEEDS_HUMAN = "needs_human"  # the human did not answer the ask-once question


class RunStatus(str, Enum):
    RUNNING = "running"
    PASSED = "passed"          # every step passed, verification not run yet
    FAILED = "failed"          # a step gave up or a budget tripped
    VERIFYING = "verifying"
    VERIFIED = "verified"
    UNVERIFIED = "unverified"


class FailureClass(str, Enum):
    DOCS_BUG = "docs_bug"
    ENVIRONMENT = "environment"
    PRODUCT_BUG = "product_bug"
    NEEDS_SECRET = "needs_secret"


class FileSpec(BaseModel):
    path: str
    content: str


class Expected(BaseModel):
    """What success looks like for one step."""
    exit_code: int = 0
    output_contains: str | None = None
    file_exists: str | None = None


class Step(BaseModel):
    """One runbook step. The planner copies `command` exactly from the docs."""
    id: int = Field(ge=1)
    intent: str
    command: str
    files: list[FileSpec] = Field(default_factory=list)
    expected: Expected = Field(default_factory=Expected)
    source_line: str = ""
    skipped_out_of_scope: bool = False   # paid account, video, GUI: the planner keeps the step but it never runs
    skip_reason: str = ""


class Runbook(BaseModel):
    source_url: str
    title: str = ""
    image: str = "python:3.11-slim"
    docs_markdown: str = ""
    steps: list[Step]


class StepResult(BaseModel):
    step_id: int
    command: str
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    duration_s: float = 0.0
    timed_out: bool = False
    passed: bool = False
    server_ready: bool = False   # a dev server step that reached "listening" and was then stopped


class Classification(BaseModel):
    """Probabilities per failure class. `top` is the class with the highest probability."""
    probabilities: dict[FailureClass, float]
    source: str = "judge"        # judge, claude, precedent or human

    @property
    def top(self) -> FailureClass:
        return max(self.probabilities, key=lambda c: self.probabilities[c])

    @property
    def confidence(self) -> float:
        return self.probabilities[self.top]


class Patch(BaseModel):
    step_id: int
    old_command: str
    new_command: str
    reason: str
    failure_class: FailureClass = FailureClass.DOCS_BUG
    source: str = ""           # where the fix came from: registry, search URL, issue


class GaveUp(BaseModel):
    step_id: int
    reason: str
    failure_class: FailureClass | None = None


class Budget(BaseModel):
    attempts_per_step: int = 3
    tool_calls_per_run: int = 25
    cost_usd_per_run: float = 0.50
    seconds_per_step: int = 300


class Usage(BaseModel):
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0      # list price, not billed


class RunState(BaseModel):
    """Checkpoint written to runs/<run_id>/state.json after every step."""
    run_id: str
    source_url: str
    status: RunStatus = RunStatus.RUNNING
    step_status: dict[int, StepStatus] = Field(default_factory=dict)
    attempts: dict[int, int] = Field(default_factory=dict)
    results: list[StepResult] = Field(default_factory=list)
    last_good_step: int = 0
    first_failed_step: int | None = None
    patches: list[Patch] = Field(default_factory=list)
    gave_up: list[GaveUp] = Field(default_factory=list)
    classifications: dict[int, Classification] = Field(default_factory=dict)
    usage: Usage = Field(default_factory=Usage)
    started_at: str = ""
    finished_at: str = ""
    time_to_first_success_s: float | None = None
    tags: list[str] = Field(default_factory=list)
    stop_reason: str = ""
