"""Agent hardening: redundant cd, recovery drift, reported failed step, SIGPIPE."""

from __future__ import annotations

import pytest

from onestrun import cli, recovery, sandbox
from onestrun.models import GaveUp, RunState, RunStatus, StepResult, StepStatus
from onestrun.planner import SYSTEM_PROMPT
from onestrun.report import reported_failed_step


def test_leading_cd_is_guarded_for_execution_only():
    out = sandbox.guard_leading_cd("cd proj && pip install -e .")
    assert out == '{ [ "$(basename "$PWD")" = "proj" ] || cd proj; } && pip install -e .'
    assert sandbox.guard_leading_cd("pip install x") == "pip install x"
    assert sandbox.guard_leading_cd("cd -P x && ls") == "cd -P x && ls"
    assert sandbox.guard_leading_cd("cd a/b && ls") == "cd a/b && ls"


@pytest.mark.live
def test_guarded_cd_runs_in_a_container_when_already_inside():
    """In a real container, a step that starts with cd <dir> works from inside <dir>."""
    from onestrun.sandbox import Container

    with Container(name="1stRun-t7-cdguard-test") as c:
        assert c.exec("mkdir -p proj && cd proj").exit_code == 0
        r = c.exec("cd proj && echo ok")
        assert r.exit_code == 0 and "ok" in r.stdout


def test_prefix_maps_sigpipe_exit_to_zero():
    assert "-eq 141" in sandbox._PREFIX


def test_planner_prompt_forbids_extra_cd():
    assert "never add a cd the docs do not show" in SYSTEM_PROMPT


def test_drift_detection():
    old = "pip install --editable . --group dev"
    assert recovery.drifted(old, "dagster project from-example --name x")
    assert not recovery.drifted(old, "pip install --editable . --group dev --upgrade")
    assert not recovery.drifted("cd app && npm install", "cd app && npm install --legacy-peer-deps")
    assert not recovery.drifted("sudo apt-get install -y git", "apt-get update && apt-get install -y git")


def test_ask_fix_rejects_drift(monkeypatch):
    from onestrun.models import Budget, FailureClass, Step

    monkeypatch.setattr(recovery.llm, "ask_json", lambda *a, **k: (
        {"new_command": "dagster project from-example --name x", "reason": "r", "source": "s"}, {}))
    monkeypatch.setattr(recovery, "_add_usage", lambda *a, **k: None)
    monkeypatch.setattr(recovery.budget_mod, "check", lambda *a, **k: None)
    step = Step(id=3, intent="install", command="pip install --editable . --group dev")
    res = recovery._ask_fix("p", (), 1, RunState(run_id="r", source_url="u"), Budget(), step,
                            step.command, FailureClass.DOCS_BUG, [])
    assert isinstance(res, GaveUp) and "drifted from the docs command" in res.reason


def test_reported_step_is_the_gave_up_one():
    st = RunState(run_id="r", source_url="u", status=RunStatus.FAILED, first_failed_step=1)
    st.step_status = {1: StepStatus.PASSED, 2: StepStatus.PASSED, 3: StepStatus.GAVE_UP}
    st.gave_up = [GaveUp(step_id=3, reason="x")]
    assert reported_failed_step(st) == 3
    st.gave_up = []
    assert reported_failed_step(st) == 3
    line = cli._summary(st, {1: "a", 2: "b", 3: "c"})[0]
    assert "step 3/3" in line


def test_exec_applies_the_cd_guard(monkeypatch):
    """The guard must run inside Container.exec, not only as a helper."""
    import subprocess

    from onestrun import sandbox

    seen = {}

    class FakeProc:
        returncode = 0

        def communicate(self, input=None, timeout=None):
            seen["script"] = input.decode() if isinstance(input, bytes) else input
            return (b"", b"")

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: FakeProc())
    c = sandbox.Container.__new__(sandbox.Container)
    c.name = "1stRun-t-test"
    c.exec("cd proj && ls", timeout_s=5)
    assert sandbox.guard_leading_cd("cd proj && ls") in seen["script"]


def test_prefix_defines_cd_noop_when_already_inside():
    assert 'cd() {' in sandbox._PREFIX and 'builtin cd "$@"' in sandbox._PREFIX


@pytest.mark.live
def test_mid_command_cd_works_from_inside_the_folder():
    """A patch can put cd in the middle of a chain. The cd function must cover that too."""
    from onestrun.sandbox import Container

    with Container(name="1stRun-t7-cdmid-test") as c:
        c.exec("mkdir -p proj && cd proj")
        r = c.exec("echo start && cd proj && echo ok")
        assert r.exit_code == 0 and "ok" in r.stdout
        assert c.exec("cd /work && cd missing").exit_code != 0
