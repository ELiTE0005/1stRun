"""Track T5. Model-free re-run of the patched runbook in a brand-new container.

This file must never import the planner, recovery or llm modules. A test enforces it.
"""

from __future__ import annotations

import uuid
from typing import Any, Callable

from firstrun import tracing

from firstrun import config
from firstrun.tracing import mark_error, set_io
from firstrun.models import FileSpec, Patch, Runbook, RunStatus, StepResult

PINS_PATH = "/tmp/fr_pins.txt"


def apply_patches(runbook: Runbook, patches: list[Patch]) -> Runbook:
    """Return a deep copy with each patched step's command replaced. The last patch per step wins."""
    patched = runbook.model_copy(deep=True)
    latest: dict[int, Patch] = {}
    for patch in patches:
        latest[patch.step_id] = patch
    for step in patched.steps:
        if step.id in latest:
            step.command = latest[step.id].new_command
    return patched


def _default_factory(image: str, name: str):
    from firstrun.sandbox import Container

    return Container(image=image, name=name)


def _default_run_step(container, step) -> StepResult:
    from firstrun.executor import run_step

    return run_step(container, step)


def _run(
    runbook: Runbook,
    patches: list[Patch],
    container_factory: Callable[[str, str], Any] | None,
    run_step: Callable[[Any, Any], StepResult] | None,
    pins: str = "",
) -> tuple[RunStatus, dict]:
    factory = container_factory or _default_factory
    runner = run_step or _default_run_step
    patched = apply_patches(runbook, patches)
    name = f"firstrun-verify-{uuid.uuid4().hex[:8]}"
    details: dict = {"container": name, "image": patched.image, "steps": [], "failed_step": None, "reason": ""}

    with tracing.trace("verify", kind="GUARDRAIL") as span, config.block_model_calls():
        try:
            with factory(patched.image, name) as container:
                if pins.strip():
                    # Pin the package versions of the recovery run, so a new release cannot change the result.
                    container.write_files([FileSpec(path=PINS_PATH, content=pins)])
                    container.exec(f"export PIP_CONSTRAINT={PINS_PATH}", timeout_s=30)
                    details["pinned"] = len([ln for ln in pins.splitlines() if ln.strip()])
                for step in patched.steps:
                    if step.skipped_out_of_scope:
                        continue
                    result = runner(container, step)
                    details["steps"].append(
                        {
                            "step_id": step.id,
                            "command": step.command,
                            "passed": bool(result.passed),
                            "duration_s": result.duration_s,
                        }
                    )
                    if not result.passed:
                        details["failed_step"] = step.id
                        details["reason"] = f"step {step.id} failed (exit {result.exit_code})"
                        tracing.log("verify failed at step {id}", id=step.id, command=step.command, exit_code=result.exit_code)
                        break
        except config.ModelCallBlocked as exc:
            details["reason"] = f"model call during verification: {exc}"
            tracing.log("verify blocked a model call: {err}", level="error", err=str(exc))
        except Exception as exc:  # a broken container counts as unverified
            details["reason"] = f"verification error: {exc}"
            tracing.log("verify error: {err}", err=str(exc))

        runnable = [st for st in patched.steps if not st.skipped_out_of_scope]
        passed = not details["reason"] and len(details["steps"]) == len(runnable)
        if passed:
            details["reason"] = f"all {len(runnable)} steps passed in a fresh container, no model calls"
        span.set_attribute("guardrail.passed", passed)
        span.set_attribute("guardrail.reason", details["reason"])
        set_io(span, input={"steps": len(patched.steps), "patches": len(patches), "image": patched.image},
               output={"passed": passed, "reason": details["reason"], "steps": details["steps"]})
        if not passed:
            mark_error(span, details["reason"])

    return (RunStatus.VERIFIED if passed else RunStatus.UNVERIFIED), details


def verify(
    runbook: Runbook,
    patches: list[Patch],
    container_factory: Callable[[str, str], Any] | None = None,
    run_step: Callable[[Any, Any], StepResult] | None = None,
    out: dict | None = None,
    pins: str = "",
) -> RunStatus:
    """GUARDRAIL span `verify`. Returns RunStatus.VERIFIED or RunStatus.UNVERIFIED. Never calls a model.

    `container_factory(image, name)` returns a context manager. `out`, when given, receives the details.
    """
    status, details = _run(runbook, patches, container_factory, run_step, pins)
    if out is not None:
        out.update(details)
        out["status"] = status.value
    return status


def verify_details(
    runbook: Runbook,
    patches: list[Patch],
    container_factory: Callable[[str, str], Any] | None = None,
    run_step: Callable[[Any, Any], StepResult] | None = None,
) -> dict:
    """Same run as verify(), returned as a dict: status, per-step pass/fail and duration, reason."""
    out: dict = {}
    verify(runbook, patches, container_factory, run_step, out)
    return out
