"""report.md names the first failure, and the stopping step when they differ. Offline."""

from __future__ import annotations

from onestrun import report
from onestrun.models import GaveUp, RunState, RunStatus, Runbook, Step, StepResult, StepStatus


def _write(tmp_path, monkeypatch, state):
    monkeypatch.setattr(report, "run_dir", lambda rid: tmp_path)
    rb = Runbook(source_url="https://docs.x.io", steps=[Step(id=i, intent=f"s{i}", command=f"cmd{i}") for i in (1, 2, 3)])
    return report.write_report(state, rb).read_text(encoding="utf-8")


def test_same_step_keeps_first_failed_heading(tmp_path, monkeypatch):
    st = RunState(run_id="r", source_url="https://docs.x.io", status=RunStatus.FAILED, first_failed_step=2,
                  step_status={1: StepStatus.PASSED, 2: StepStatus.FAILED},
                  results=[StepResult(step_id=2, command="cmd2", exit_code=1)])
    md = _write(tmp_path, monkeypatch, st)
    assert "## First Failed Step" in md and "Step 2 of 3" in md


def test_recovered_then_stopped_names_both(tmp_path, monkeypatch):
    st = RunState(run_id="r", source_url="https://docs.x.io", status=RunStatus.FAILED, first_failed_step=1,
                  step_status={1: StepStatus.PASSED, 2: StepStatus.PASSED, 3: StepStatus.GAVE_UP},
                  gave_up=[GaveUp(step_id=3, reason="cost budget spent")],
                  results=[StepResult(step_id=1, command="cmd1", exit_code=127),
                           StepResult(step_id=1, command="fix1", exit_code=0, passed=True),
                           StepResult(step_id=3, command="cmd3", exit_code=2)])
    md = _write(tmp_path, monkeypatch, st)
    assert "## First Failed Step" not in md
    assert "## The Step That Ended the Run" in md and "Step 3 of 3" in md
    assert "The first failure was step 1: `cmd1`. Recovery fixed it." in md
