"""Edge cases V1-V5 (verification must not cheat)."""

from __future__ import annotations

import pytest

from _edge_fakes import FakeContainer, factory_for, make_runbook
from firstrun import classify, config, executor, llm, patch, verify as verify_mod
from firstrun import state as state_io
from firstrun.models import Expected, Patch, Runbook, RunState, RunStatus, Step, StepResult
from firstrun.sandbox import Container


def _live(tag):
    return lambda image, name=None: Container(image, name=f"firstrun-t7-{tag}")


@pytest.fixture
def t7_cleanup():
    import subprocess

    yield
    ids = subprocess.run([*config.DOCKER_CMD, "ps", "-aq", "--filter", "name=firstrun-t7-"],
                         capture_output=True).stdout.decode().split()
    if ids:
        subprocess.run([*config.DOCKER_CMD, "rm", "-f", *ids], capture_output=True)


# --- V1 ------------------------------------------------------------------------

@pytest.mark.live
def test_v1_live_patch_that_only_works_in_the_recovery_run_is_unverified(tmp_runs_dir, t7_cleanup):
    # Attempt 1 leaves /work/m behind and fails. The patch needs that leftover, so a clean container fails it.
    rb = Runbook(source_url="https://docs.example.com/v1", steps=[
        Step(id=1, intent="setup", command="test -e /work/m || (touch /work/m; exit 1)")])

    def recover(step, result, state, docs):
        return Patch(step_id=step.id, old_command=step.command, new_command="test -e /work/m", reason="leftover")

    state = executor.run(
        rb, run_id="v1", recover=recover, container_factory=lambda image=None, **kw: Container(image, name="firstrun-t7-v1a"),
        verify=lambda r, s: verify_mod.verify(r, s.patches, container_factory=_live("v1b")),
    )
    assert state.step_status[1].value == "passed"          # it passed in the recovery run
    assert state.status == RunStatus.UNVERIFIED            # and failed in the clean one
    assert patch.write_outputs(tmp_runs_dir / "v1", state, rb) == []


# --- V2 ------------------------------------------------------------------------

def test_v2_a_model_call_during_verification_is_blocked_and_unverified(monkeypatch):
    rb = make_runbook("echo one", "echo two")
    attempts = []

    def sneaky(container, step):
        attempts.append(step.id)
        llm.ask("what should this command be?")            # a model call inside verification
        return StepResult(step_id=step.id, command=step.command, exit_code=0, passed=True)

    monkeypatch.setattr(llm, "_run", lambda *a, **k: pytest.fail("the model was reached"))
    out: dict = {}
    status = verify_mod.verify(rb, [], container_factory=lambda image, name: FakeContainer(), run_step=sneaky, out=out)
    assert status == RunStatus.UNVERIFIED and attempts == [1]
    assert "model call" in out["reason"]
    assert config._blocked == 0                            # the block is lifted afterwards


def test_v2_jev_classification_is_blocked_too():
    with config.block_model_calls():
        with pytest.raises(config.ModelCallBlocked):
            classify.classify("err", "cmd")


# --- V3 ------------------------------------------------------------------------

def test_v3_pins_are_written_and_exported_before_step_1():
    fake = FakeContainer()
    verify_mod.verify(make_runbook("pip install six"), [], container_factory=lambda image, name: fake,
                      run_step=lambda c, s: StepResult(step_id=s.id, command=s.command, exit_code=0, passed=True),
                      pins="six==1.16.0\n")
    assert fake.written[verify_mod.PINS_PATH] == "six==1.16.0\n"
    assert fake.log[0] == f"export PIP_CONSTRAINT={verify_mod.PINS_PATH}"


def test_v3_no_pins_means_no_extra_commands():
    fake = FakeContainer()
    verify_mod.verify(make_runbook("echo a"), [], container_factory=lambda image, name: fake,
                      run_step=lambda c, s: StepResult(step_id=s.id, command=s.command, exit_code=0, passed=True))
    assert fake.log == [] and fake.written == {}


def test_v3_freeze_output_keeps_plain_pins_only():
    freeze = "six==1.16.0\npip==24.0\nsetuptools==69.0\n-e git+https://x#egg=y\nfoo @ file:///tmp/foo\nRequests==2.31.0\n"
    assert executor.parse_pins(freeze) == "six==1.16.0\nRequests==2.31.0\n"


@pytest.mark.live
def test_v3_live_recovery_versions_are_captured_and_pinned_in_the_clean_run(tmp_runs_dir, t7_cleanup):
    rb = Runbook(source_url="https://docs.example.com/v3", steps=[
        Step(id=1, intent="install", command="pip install six==99.0.0")])

    def recover(step, result, state, docs):
        return Patch(step_id=step.id, old_command=step.command, new_command="pip install six==1.16.0", reason="typo")

    def verify(r, s):
        pins = state_io.load_pins(s.run_id)
        assert "six==1.16.0" in pins
        return verify_mod.verify(r, s.patches, container_factory=_live("v3b"), pins=pins)

    state = executor.run(rb, run_id="v3", recover=recover, verify=verify,
                         container_factory=lambda image=None, **kw: Container(image, name="firstrun-t7-v3a"))
    assert state.status == RunStatus.VERIFIED


@pytest.mark.live
def test_v3_live_pin_beats_a_newer_release(t7_cleanup):
    """Pin six to an older release. A drifted index would hand out the newest, the pin must win."""
    rb = Runbook(source_url="https://docs.example.com/v3b", steps=[
        Step(id=1, intent="install", command="pip install six && pip show six",
             expected=Expected(output_contains="Version: 1.16.0"))])
    status = verify_mod.verify(rb, [], container_factory=_live("v3c"), pins="six==1.16.0\n")
    assert status == RunStatus.VERIFIED


# --- V4 ------------------------------------------------------------------------

def _verified_state():
    return RunState(run_id="v4", source_url="u", status=RunStatus.VERIFIED)


def test_v4_no_patches_means_no_diff_and_no_pr_body(tmp_path):
    rb = make_runbook("echo a", docs_markdown="```bash\necho a\n```\n")
    assert patch.write_outputs(tmp_path, _verified_state(), rb) == []
    assert list(tmp_path.iterdir()) == []


def test_v4_a_patch_that_changes_nothing_writes_nothing(tmp_path):
    rb = make_runbook("echo a", docs_markdown="```bash\necho a\n```\n")
    state = _verified_state()
    state.patches = [Patch(step_id=1, old_command="echo a", new_command="echo a", reason="same")]
    assert patch.write_outputs(tmp_path, state, rb) == []
    assert list(tmp_path.iterdir()) == []


# --- V5 ------------------------------------------------------------------------

def test_v5_clean_pass_is_passed_with_no_patch_and_no_pr_text(tmp_runs_dir):
    rb = make_runbook("echo a", "echo b", docs_markdown="```bash\necho a\necho b\n```\n")
    state = executor.run(rb, run_id="v5", container_factory=factory_for(FakeContainer()),
                         verify=lambda r, s: pytest.fail("a clean pass has nothing to verify"))
    assert state.status == RunStatus.PASSED and state.patches == []
    assert "Verdict:** pass" in (tmp_runs_dir / "v5" / "report.md").read_text(encoding="utf-8")
    assert patch.write_outputs(tmp_runs_dir / "v5", state, rb) == []
    assert not (tmp_runs_dir / "v5" / "patch.diff").exists() and not (tmp_runs_dir / "v5" / "pr_body.md").exists()
