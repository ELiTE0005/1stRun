"""Track T4. Hard limits. Each check is a GUARDRAIL span `budget`."""

from __future__ import annotations

from firstrun import tracing

from firstrun.models import Budget, RunState
from firstrun.tracing import mark_error, set_io


class BudgetExceeded(Exception):
    pass


def _trip_reason(state: RunState, budget: Budget, step_id: int | None) -> str | None:
    if step_id is not None and state.attempts.get(step_id, 0) >= budget.attempts_per_step:
        return f"attempt budget spent: step {step_id} used {budget.attempts_per_step} attempts"
    if state.usage.tool_calls >= budget.tool_calls_per_run:
        return f"tool call budget spent: {state.usage.tool_calls} of {budget.tool_calls_per_run} calls"
    if state.usage.cost_usd >= budget.cost_usd_per_run:
        return f"cost budget spent: ${state.usage.cost_usd:.4f} of ${budget.cost_usd_per_run:.4f}"
    return None


def check(state: RunState, budget: Budget, step_id: int | None = None) -> None:
    """Raise BudgetExceeded when a limit trips."""
    with tracing.trace("budget", kind="GUARDRAIL") as gspan:
        reason = _trip_reason(state, budget, step_id)
        set_io(gspan, input={"step_id": step_id, "attempts": state.attempts.get(step_id, 0) if step_id else None,
                             "cost_usd": round(state.usage.cost_usd, 4)},
               output={"passed": reason is None, "reason": reason})
        if reason:
            mark_error(gspan, reason)
        gspan.set_attribute("guardrail.name", "budget")
        gspan.set_attribute("guardrail.passed", reason is None)
        gspan.set_attribute("guardrail.triggered", reason is not None)
        if reason:
            gspan.set_attribute("guardrail.reason", reason)
    if reason:
        raise BudgetExceeded(reason)
