"""Track T2. Runs a runbook step by step and checkpoints after each step."""

from __future__ import annotations

import contextlib
import re
import shlex
import time
from datetime import datetime, timezone
from typing import Callable

from firstrun import tracing

from firstrun import budget as budget_mod, report, state as state_io
from firstrun.budget import BudgetExceeded
from firstrun.redact import redact
from firstrun.models import (
    Budget, GaveUp, Patch, Runbook, RunState, RunStatus, Step, StepResult, StepStatus,
)
from firstrun.sandbox import Container, DockerUnavailable
from firstrun.tracing import mark_error, set_io

# recover(step, result, state, docs_markdown) -> Patch | GaveUp
RecoverFn = Callable[[Step, StepResult, RunState, str], "Patch | GaveUp"]


# A quickstart often ends by starting a dev server, which never exits on its own. Such a step passes when its
# output says the server is listening, then the server is stopped.
SERVER_WINDOW_S = 90
_SERVER_CMD = re.compile(
    r"\bflask\b.*\brun\b|\buvicorn\b|\bfastapi\s+(dev|run)\b|\bgunicorn\b|\bhypercorn\b|manage\.py\s+runserver|"
    r"\blitestar\b.*\brun\b|python3?\s+-m\s+http\.server|\bstreamlit\s+run\b|\bmkdocs\s+serve\b|"
    r"\b(npm|pnpm|yarn)\s+(run\s+)?(dev|start|serve)\b|\bnext\s+dev\b|\bvite\b(?!\s+build)|\bhugo\s+server\b|"
    r"\bjekyll\s+serve\b|\brails\s+s(erver)?\b|\bphp\s+artisan\s+serve\b|\bpython3?\s+app\.py\b")
_SERVER_READY = re.compile(
    r"Running on https?://|Uvicorn running on|Application startup complete|Starting development server at|"
    r"Serving HTTP on|[Ll]istening on|Local:\s+https?://|ready in \d|Server started|serving at|Serving on|"
    r"You can now view .* in your browser|Booting worker|started server on")


# An install names server packages (pip install uvicorn) without starting one, so it keeps the full timeout.
_INSTALL = re.compile(r"^\s*(sudo\s+)?(pip3?|python3?\s+-m\s+pip|uv(\s+pip)?|poetry|pipx|conda|npm|pnpm|yarn|bun|"
                      r"apt(-get)?|brew|gem|cargo|go)\s+(install|add|i)\b")


def is_server_command(command: str) -> bool:
    return any(_SERVER_CMD.search(part) and not _INSTALL.search(part)
               for part in re.split(r"&&|\|\||;|\||\n", command))


def server_ready(result: StepResult) -> bool:
    return result.timed_out and bool(_SERVER_READY.search(result.stdout + "\n" + result.stderr))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def check_expected(step: Step, result: StepResult, container: Container | None = None,
                   start_dir: str = "") -> bool:
    """True when the result meets step.expected. file_exists needs the container."""
    exp = step.expected
    if result.server_ready:
        # The server came up and FirstRun stopped it, so its exit code says nothing about the docs.
        return exp.output_contains is None or exp.output_contains in (result.stdout + result.stderr)
    if result.timed_out or result.exit_code != exp.exit_code:
        return False
    if exp.output_contains is not None and exp.output_contains not in (result.stdout + result.stderr):
        return False
    if exp.file_exists:
        if container is None:
            return False
        # A relative path counts from where the step started, since the step may cd away.
        path = shlex.quote(exp.file_exists)
        check = f"test -e {path}" + (f" || (cd {shlex.quote(start_dir)} && test -e {path})" if start_dir else "")
        # Planners write paths from the run root, /work, even when a retry starts in a subfolder.
        check += f" || (cd /work && test -e {path})"
        probe = container.exec(check, timeout_s=30)
        if probe.exit_code != 0:
            return False
    return True


def run_step(container: Container, step: Step, timeout_s: int | None = None) -> StepResult:
    """TOOL span `step.<id>`. Writes the step's files, runs its command, checks `expected`."""
    timeout_s = timeout_s or Budget().seconds_per_step
    with tracing.trace(f"step.{step.id}", kind="TOOL") as span:
        started = time.monotonic()
        if step.files:
            container.write_files(step.files)
        start_dir = ""
        if step.expected.file_exists:
            start_dir = container.exec("pwd", timeout_s=30).stdout.strip()
        serving = is_server_command(step.command)
        if serving:
            try:  # stop as soon as the server says it listens, instead of waiting out the window
                result = container.exec(step.command, timeout_s=min(timeout_s, SERVER_WINDOW_S), ready=_SERVER_READY)
            except TypeError:  # a container without early stop
                result = container.exec(step.command, timeout_s=min(timeout_s, SERVER_WINDOW_S))
        else:
            result = container.exec(step.command, timeout_s=timeout_s)
        result.server_ready = serving and server_ready(result)
        result.step_id = step.id
        result.command = step.command
        result.stdout, result.stderr = redact(result.stdout), redact(result.stderr)  # never keep a secret
        result.passed = check_expected(step, result, container, start_dir)
        result.duration_s = round(time.monotonic() - started, 3)
        span.set_attribute("step.command", step.command)
        span.set_attribute("step.exit_code", result.exit_code)
        span.set_attribute("step.duration", result.duration_s)
        span.set_attribute("step.passed", result.passed)
        span.set_attribute("step.server_ready", result.server_ready)
        set_io(span,
               input={"step_id": step.id, "command": step.command, "files": [f.path for f in step.files]},
               output={"exit_code": result.exit_code, "passed": result.passed, "timed_out": result.timed_out,
                       "server_ready": result.server_ready,
                       "stdout": result.stdout[-2000:], "stderr": result.stderr[-2000:]})
        if not result.passed:
            mark_error(span, f"step {step.id} failed (exit {result.exit_code})")
    return result


def _effective_command(state: RunState, step: Step) -> Step:
    """The step with the latest patch applied, so a resume replays the fixed command."""
    for patch in reversed(state.patches):
        if patch.step_id == step.id:
            return step.model_copy(update={"command": patch.new_command})
    return step


def _elapsed(state: RunState) -> float:
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(state.started_at)).total_seconds()
    except ValueError:
        return 0.0


def _stop(state: RunState, status: RunStatus, reason: str = "") -> None:
    state.status = status
    if reason:
        state.stop_reason = reason
    state.finished_at = _now()


def run(
    runbook: Runbook,
    run_id: str | None = None,
    resume: bool = False,
    tags: list[str] | None = None,
    recover: RecoverFn | None = None,
    budget: Budget | None = None,
    container_factory: Callable[..., Container] = Container,
    verify: Callable[[Runbook, RunState], RunStatus] | None = None,
    trace: bool = True,
) -> RunState:
    """WORKFLOW span `firstrun.run`. Writes runbook.json, state.json after each step, then report.md."""
    budget = budget or Budget()
    if resume:
        if not run_id:
            raise ValueError("resume needs a run_id")
        state = state_io.load_state(run_id)
        runbook = state_io.load_runbook(run_id)
        state.status = RunStatus.RUNNING
        state.stop_reason = ""
        state.finished_at = ""
    else:
        run_id = run_id or state_io.new_run_id(runbook.source_url)
        state = RunState(
            run_id=run_id, source_url=runbook.source_url, started_at=_now(),
            tags=list(tags or []),
            step_status={s.id: StepStatus.PENDING for s in runbook.steps},
        )
        state_io.save_runbook(run_id, runbook)
    tags = state.tags
    state_io.save_state(state)

    attrs = {
        "target": state_io.target_name(runbook.source_url),
        "run_id": state.run_id,
        "variant": tags[0] if tags else "dev",
        "tags": list(tags),
    }
    try:
        # trace=False when the caller already opened the run trace around planning.
        ctx = tracing.trace("firstrun.run", kind="WORKFLOW", **attrs) if trace else contextlib.nullcontext()
        with ctx:
            try:
                _execute(runbook, state, recover, budget, container_factory, capture_pins=verify is not None)
            except DockerUnavailable as exc:
                # Raised only while the container starts, so no step ran and no partial state exists.
                _stop(state, RunStatus.FAILED, str(exc))
                state_io.save_state(state)
                _safe_report(state, runbook)
                return state
            # A clean pass has nothing to verify: no patch was made.
            if verify is not None and state.status == RunStatus.PASSED and state.patches:
                state.status = RunStatus.VERIFYING
                state_io.save_state(state)
                state.status = verify(runbook, state)
                state.finished_at = _now()
    except BaseException as exc:  # save what we know, then let the error out
        if state.status == RunStatus.RUNNING:
            reason = "interrupted" if isinstance(exc, KeyboardInterrupt) else f"error: {exc!r}"
            _stop(state, RunStatus.FAILED, reason)
        state_io.save_state(state)
        _safe_report(state, runbook)
        raise
    state_io.save_state(state)
    report.write_report(state, runbook)
    return state


def _safe_report(state: RunState, runbook: Runbook) -> None:
    try:
        report.write_report(state, runbook)
    except Exception:
        pass


def _execute(runbook, state, recover, budget, container_factory, capture_pins: bool = False) -> None:
    with container_factory(runbook.image) as container:
        # Rebuild the environment of a resumed run. Replays are not recorded as results.
        for step in runbook.steps:
            if step.id > state.last_good_step:
                break
            if step.skipped_out_of_scope:
                continue
            eff = _effective_command(state, step)
            res = run_step(container, eff, budget.seconds_per_step)
            tracing.log("replayed step {id}", id=step.id)
            if not res.passed:
                state.step_status[step.id] = StepStatus.FAILED
                state.first_failed_step = state.first_failed_step or step.id
                _stop(state, RunStatus.FAILED, f"replay of step {step.id} failed")
                state_io.save_state(state)
                return

        for step in runbook.steps:
            if step.id <= state.last_good_step:
                continue
            if step.skipped_out_of_scope:
                state.step_status[step.id] = StepStatus.SKIPPED
                tracing.log("step {id} skipped: {why}", id=step.id, why=step.skip_reason)
                continue
            if not _run_with_recovery(container, step, state, recover, budget, runbook):
                state_io.save_state(state)
                return
            state_io.save_state(state)

        if capture_pins and state.patches:  # only a patched run is verified, and verification pins these versions
            _save_pins(container, state)

    state.time_to_first_success_s = round(_elapsed(state), 1)
    _stop(state, RunStatus.PASSED)


def _run_with_recovery(container, step: Step, state: RunState, recover, budget: Budget, runbook: Runbook) -> bool:
    """Run one step until it passes, a patch budget runs out, or recovery gives up."""
    current = _effective_command(state, step)
    while True:
        state.attempts[step.id] = state.attempts.get(step.id, 0) + 1
        state.step_status[step.id] = StepStatus.RUNNING
        result = run_step(container, current, budget.seconds_per_step)
        state.results.append(result)
        if result.passed:
            state.step_status[step.id] = StepStatus.PASSED
            state.last_good_step = step.id
            return True

        state.step_status[step.id] = StepStatus.FAILED
        if state.first_failed_step is None:
            state.first_failed_step = step.id
        state_io.save_state(state)
        if recover is None:
            _stop(state, RunStatus.FAILED, f"step {step.id} failed")
            return False
        try:
            budget_mod.check(state, budget, step.id)  # GUARDRAIL span `budget`
        except BudgetExceeded as exc:
            state.step_status[step.id] = StepStatus.GAVE_UP
            state.gave_up.append(GaveUp(step_id=step.id, reason=str(exc)))
            _stop(state, RunStatus.FAILED, f"step {step.id} gave up: {exc}")
            return False

        state.step_status[step.id] = StepStatus.RECOVERING
        decision = recover(current, result, state, runbook.docs_markdown)
        if isinstance(decision, GaveUp):
            human = decision.reason.startswith("needs_human")
            state.step_status[step.id] = StepStatus.NEEDS_HUMAN if human else StepStatus.GAVE_UP
            state.gave_up.append(decision)
            _stop(state, RunStatus.FAILED, f"step {step.id} gave up: {decision.reason}")
            return False
        state.patches.append(decision)
        current = current.model_copy(update={"command": decision.new_command})


_PIN = re.compile(r"^[A-Za-z0-9_.\-]+==[^\s;]+$")
_NOT_PINNED = {"pip", "setuptools", "wheel"}


def parse_pins(freeze_output: str) -> str:
    """Keep plain name==version lines from `pip freeze`. Tool packages stay free so pip can upgrade itself."""
    keep = [ln.strip() for ln in freeze_output.splitlines()
            if _PIN.match(ln.strip()) and ln.split("==")[0].strip().lower() not in _NOT_PINNED]
    return "\n".join(keep) + ("\n" if keep else "")


def _save_pins(container, state: RunState) -> None:
    """Write the package versions of the recovery run to runs/<run_id>/pins.txt, for verification to pin."""
    try:
        res = container.exec("pip freeze 2>/dev/null || true", timeout_s=60)
        text = parse_pins(res.stdout) if res.exit_code == 0 else ""
        if text:
            state_io.save_pins(state.run_id, text)
    except Exception:  # pinning is best effort and never fails a run
        pass
