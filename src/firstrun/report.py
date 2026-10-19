"""Track T2. Writes runs/<run_id>/report.md and the cross-run summary table."""

from __future__ import annotations

from pathlib import Path

from firstrun import config
from firstrun.redact import redact
from firstrun.models import Runbook, RunState, RunStatus, StepResult, StepStatus
from firstrun.state import run_dir, target_name

VERDICTS = {
    RunStatus.RUNNING: "unfinished",
    RunStatus.PASSED: "pass",
    RunStatus.FAILED: "fail",
    RunStatus.VERIFYING: "verifying",
    RunStatus.VERIFIED: "verified",
    RunStatus.UNVERIFIED: "unverified",
}


def is_fixture(source_url: str) -> bool:
    """A saved docs page or a web archive snapshot. Reports label it, so nobody reads it as live docs."""
    low = source_url.lower()
    return "_fixture" in low or "web.archive.org" in low


def _cell(text: str, width: int = 60) -> str:
    text = " ".join(str(text).split()).replace("|", "\\|")
    return text if len(text) <= width else text[: width - 1] + "…"


def reported_failed_step(state: RunState) -> int | None:
    """The step that ended the run: the last gave-up step, else the highest failed or gave-up step id."""
    if state.gave_up:
        return state.gave_up[-1].step_id
    bad = [i for i, st in state.step_status.items() if st in (StepStatus.FAILED, StepStatus.GAVE_UP)]
    return max(bad) if bad else state.first_failed_step


def _last_failed(state: RunState, step_id: int) -> StepResult | None:
    for r in reversed(state.results):
        if r.step_id == step_id and not r.passed:
            return r
    return None


def _first_error_line(result: StepResult | None) -> str:
    if result is None:
        return ""
    for text in (result.stderr, result.stdout):
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if lines:
            return lines[-1]
    return "timed out" if result.timed_out else f"exit {result.exit_code}"


def _duration(state: RunState) -> float | None:
    if state.time_to_first_success_s is not None:
        return state.time_to_first_success_s
    return sum(r.duration_s for r in state.results) or None


def write_report(state: RunState, runbook: Runbook) -> Path:
    total = len(runbook.steps)
    passed = sum(1 for s in state.step_status.values() if s == StepStatus.PASSED)
    commands = {s.id: s.command for s in runbook.steps}
    out: list[str] = []
    out.append(f"# FirstRun report: {runbook.title or target_name(state.source_url)}")
    out.append("")
    out.append(f"**Verdict:** {VERDICTS[state.status]} ({passed}/{total} steps passed)")
    out.append("")
    out.append(f"- Run: `{state.run_id}`")
    out.append(f"- Source: {state.source_url}")
    if is_fixture(state.source_url):
        out.append("- Source type: fixture (a saved copy of a docs page, not the live docs)")
    if state.stop_reason:
        out.append(f"- Stop reason: {state.stop_reason}")

    fid = reported_failed_step(state)
    if fid is not None:
        failed = _last_failed(state, fid)
        first_fail = next((r for r in state.results if r.step_id == fid and not r.passed), failed)
        first = state.first_failed_step
        if first is None or first == fid:
            out += ["", "## First Failed Step", ""]
            out.append(f"Step {fid} of {total}: `{commands.get(fid, '')}`")
        else:
            # The run recovered from an earlier failure and stopped later, so name both steps.
            out += ["", "## The Step That Ended the Run", ""]
            out.append(f"Step {fid} of {total}: `{commands.get(fid, '')}`")
            out.append("")
            out.append(f"The first failure was step {first}: `{commands.get(first, '')}`. Recovery fixed it.")
        if first_fail:
            out.append("")
            out.append(f"Exit code: {first_fail.exit_code}" + (" (timed out)" if first_fail.timed_out else ""))
            tail = redact("\n".join(first_fail.stderr.splitlines()[-15:]))
            if tail.strip():
                out += ["", "Last 15 lines of stderr:", "", "```", tail, "```"]
        cls = state.classifications.get(fid)
        out += ["", "## Cause", ""]
        if cls:
            out.append(f"{cls.top.value} (confidence {cls.confidence:.0%}, source {cls.source})")
        else:
            out.append("Not classified.")
        out += ["", "## Fix", ""]
        patches = [p for p in state.patches if p.step_id == fid]
        if patches:
            for p in patches:
                out.append(f"- Step {p.step_id}: `{p.old_command}` became `{p.new_command}`. {p.reason}"
                           + (f" Source: {p.source}" if p.source else ""))
        else:
            out.append("No fix found.")
        for g in state.gave_up:
            out.append(f"- Gave up on step {g.step_id}: {g.reason}")

    out += ["", "## Numbers", ""]
    ttfs = state.time_to_first_success_s
    out.append(f"- Time to first success: {f'{ttfs:.0f} s' if ttfs is not None else 'not reached'}")
    out.append(f"- Tool calls: {state.usage.tool_calls}")
    out.append(f"- Cost: ${state.usage.cost_usd:.2f} (list price, not billed)")

    out += ["", "## Step Results", ""]
    out.append("| Step | Status | Attempts | Exit | Seconds | Command |")
    out.append("|---|---|---|---|---|---|")
    for step in runbook.steps:
        status = state.step_status.get(step.id, StepStatus.PENDING)
        last = next((r for r in reversed(state.results) if r.step_id == step.id), None)
        out.append(
            f"| {step.id} | {status.value} | {state.attempts.get(step.id, 0)} | "
            f"{last.exit_code if last else '-'} | {f'{last.duration_s:.1f}' if last else '-'} | "
            f"`{_cell(commands[step.id])}` |"
        )
    out.append("")
    path = run_dir(state.run_id) / "report.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out), encoding="utf-8")
    return path


def summary_table(runs_dir: Path | None = None) -> str:
    """Markdown table over every run in runs/."""
    runs_dir = Path(runs_dir or config.RUNS_DIR)
    rows = ["| Run | Target | Status | Steps | First failed step | Time | Cost |", "|---|---|---|---|---|---|---|"]
    for sf in sorted(runs_dir.glob("*/state.json")) if runs_dir.exists() else []:
        try:
            state = RunState.model_validate_json(sf.read_text(encoding="utf-8"))
        except ValueError:
            continue
        steps: dict[int, str] = {}
        rb = sf.parent / "runbook.json"
        if rb.exists():
            try:
                steps = {s.id: s.command for s in Runbook.model_validate_json(rb.read_text(encoding="utf-8")).steps}
            except ValueError:
                pass
        total = len(steps) or len(state.step_status)
        passed = sum(1 for s in state.step_status.values() if s == StepStatus.PASSED)
        fid = state.first_failed_step
        failed = f"{fid}: `{_cell(steps.get(fid, ''), 40)}`" if fid is not None else "-"
        t = _duration(state)
        rows.append(
            f"| {state.run_id} | {target_name(state.source_url)} | {VERDICTS[state.status]} | {passed}/{total} | "
            f"{failed} | {f'{t:.0f} s' if t is not None else '-'} | ${state.usage.cost_usd:.2f} |"
        )
    return "\n".join(rows) + "\n"
