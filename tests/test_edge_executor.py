"""Edge cases E1-E10 (executor and sandbox). Unit rows run offline. Live rows need Docker in WSL.

Every live container is named 1stRun-t7-* and removed when the test ends.
"""

from __future__ import annotations

import os
import subprocess
import threading
import time

import pytest
from click.testing import CliRunner

from _edge_fakes import FakeContainer, factory_for, make_runbook
from onestrun import config, executor, recovery, sandbox
from onestrun import state as state_io
from onestrun.cli import cli
from onestrun.models import Budget, Expected, FileSpec, FailureClass, Runbook, RunStatus, Step, StepResult, StepStatus
from onestrun.sandbox import Container, DockerUnavailable


def _docker(*args, timeout=120):
    return subprocess.run([*config.DOCKER_CMD, *args], capture_output=True, timeout=timeout)


@pytest.fixture
def t7_cleanup():
    """Remove every 1stRun-t7-* container after a live test."""
    yield
    listing = _docker("ps", "-aq", "--filter", "name=1stRun-t7-")
    ids = listing.stdout.decode().split()
    if ids:
        _docker("rm", "-f", *ids)


def live_factory(tag: str, container_cls=Container):
    return lambda image=None, **kw: container_cls(image or "python:3.11-slim", name=f"1stRun-t7-{tag}")


def live_runbook(*steps) -> Runbook:
    built = [s if isinstance(s, Step) else Step(id=i, intent=f"step {i}", command=s) for i, s in enumerate(steps, 1)]
    return Runbook(source_url="https://docs.example.com/edge", title="Edge", steps=built)


# --- E1 ------------------------------------------------------------------------

def test_e1_docker_program_missing_stops_before_step_1(tmp_runs_dir, monkeypatch):
    monkeypatch.setattr(config, "DOCKER_CMD", ["1stRun-no-such-program"])
    state = executor.run(make_runbook("echo hi"), run_id="e1a")
    assert state.status == RunStatus.FAILED
    assert state.stop_reason.startswith("docker unavailable")
    assert state.results == [] and state.last_good_step == 0
    assert "docker unavailable" in (tmp_runs_dir / "e1a" / "report.md").read_text(encoding="utf-8")


def test_e1_cli_exit_code_is_2_for_docker_unavailable(tmp_runs_dir, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DOCKER_CMD", ["1stRun-no-such-program"])
    doc = tmp_path / "d.md"
    doc.write_text("# D\n\n```bash\necho hi\n```\n", encoding="utf-8")
    result = CliRunner().invoke(cli, ["run", str(doc), "--offline", "--no-verify"])
    assert result.exit_code == 2
    assert "Docker is not running in WSL" in result.output
    assert "wsl -d Ubuntu-22.04 sudo service docker start" in result.output


@pytest.mark.live
def test_e1_live_docker_daemon_down_stops_before_step_1(tmp_runs_dir, monkeypatch):
    monkeypatch.setattr(config, "DOCKER_CMD", [*config.DOCKER_CMD, "-H", "unix:///nonexistent/1stRun-t7.sock"])
    state = executor.run(make_runbook("echo hi", "echo two"), run_id="e1b")
    assert state.status == RunStatus.FAILED
    assert "docker unavailable" in state.stop_reason
    assert state.results == [] and state.last_good_step == 0
    assert all(s == StepStatus.PENDING for s in state.step_status.values())


# --- E2 ------------------------------------------------------------------------

@pytest.mark.live
def test_e2_live_hung_step_is_killed_and_marked_failed(tmp_runs_dir, t7_cleanup):
    start = time.monotonic()
    state = executor.run(live_runbook("sleep 600", "echo never"), run_id="e2", budget=Budget(seconds_per_step=5),
                         container_factory=live_factory("e2"))
    assert time.monotonic() - start < 90
    assert state.status == RunStatus.FAILED and state.step_status[1] == StepStatus.FAILED
    assert state.results[0].timed_out and state.results[0].exit_code == 124
    assert 2 not in state.step_status or state.step_status[2] == StepStatus.PENDING


def test_e2_timeout_is_classified_environment_and_not_retried(tmp_precedents):
    from onestrun.models import RunState

    state = RunState(run_id="r", source_url="u")
    step = Step(id=1, intent="x", command="sleep 600")
    res = StepResult(step_id=1, command="sleep 600", exit_code=124, timed_out=True)
    decision = recovery.recover(step, res, state, "")
    assert decision.failure_class == FailureClass.ENVIRONMENT
    assert state.classifications[1].top == FailureClass.ENVIRONMENT
    assert "timed out" in decision.reason


# --- E3 ------------------------------------------------------------------------

def test_e3_fifty_megabytes_of_output_is_cut_with_a_marker():
    text = sandbox._tail(b"x" * (50 * 1024 * 1024))
    assert len(text) < sandbox.OUTPUT_CAP + 200
    assert text.startswith("[output truncated:")
    assert text.endswith("x")


def test_e3_exec_cuts_both_streams_and_the_run_continues(monkeypatch):
    class Proc:
        returncode = 0

        def __init__(self, *a, **k):
            pass

        def communicate(self, data, timeout=None):
            return b"o" * (50 * 1024 * 1024), b"e" * (50 * 1024 * 1024)

    monkeypatch.setattr(sandbox.subprocess, "Popen", Proc)
    res = Container("python:3.11-slim", name="1stRun-t7-fake").exec("yes")
    assert res.exit_code == 0
    assert "output truncated" in res.stdout and "output truncated" in res.stderr
    assert len(res.stdout) < sandbox.OUTPUT_CAP + 200


def test_e3_run_continues_after_a_noisy_step(tmp_runs_dir):
    fake = FakeContainer({"noisy": lambda c: (0, sandbox._tail(b"x" * (3 * 1024 * 1024)), "")})
    state = executor.run(make_runbook("noisy", "echo next"), run_id="e3", container_factory=factory_for(fake))
    assert state.status == RunStatus.PASSED and fake.log == ["noisy", "echo next"]
    assert len((tmp_runs_dir / "e3" / "state.json").read_bytes()) < 100_000


# --- E4 ------------------------------------------------------------------------

@pytest.mark.live
def test_e4_live_step_that_waits_for_input_fails_fast(tmp_runs_dir, t7_cleanup):
    steps = [Step(id=1, intent="wait for a key", command='read -p "Continue? " answer; test -n "$answer"'),
             Step(id=2, intent="python input", command='python -c "input()"')]
    for step in steps:
        state = executor.run(live_runbook(step.command), run_id=f"e4-{step.id}", container_factory=live_factory("e4"),
                             budget=Budget(seconds_per_step=60))
        result = state.results[0]
        assert state.status == RunStatus.FAILED
        assert not result.timed_out and result.duration_s < 30


# --- E5 ------------------------------------------------------------------------

class CrashAtThree(Container):
    def exec(self, command, timeout_s=300):
        if command == "echo three":
            raise KeyboardInterrupt()
        return super().exec(command, timeout_s)


@pytest.mark.live
def test_e5_live_resume_continues_at_step_3(tmp_runs_dir, t7_cleanup):
    rb = live_runbook("touch /work/a.txt", "echo two", "echo three", "test -e /work/a.txt && echo four")
    with pytest.raises(KeyboardInterrupt):
        executor.run(rb, run_id="e5", container_factory=live_factory("e5a", CrashAtThree))
    crashed = state_io.load_state("e5")
    assert crashed.last_good_step == 2 and crashed.status == RunStatus.FAILED

    resumed = executor.run(rb, run_id="e5", resume=True, container_factory=live_factory("e5b"))
    assert resumed.status == RunStatus.PASSED
    ran = [r.step_id for r in resumed.results]
    assert ran == [1, 2, 3, 4]                       # steps 1 and 2 are not recorded a second time
    assert "four" in resumed.results[3].stdout       # the replay rebuilt a.txt in the new container


def test_e5_offline_resume_skips_passed_steps(tmp_runs_dir):
    class Crash(FakeContainer):
        def exec(self, command, timeout_s=300):
            if command == "echo three":
                raise KeyboardInterrupt()
            return super().exec(command, timeout_s)

    rb = make_runbook("echo one", "echo two", "echo three", "echo four")
    with pytest.raises(KeyboardInterrupt):
        executor.run(rb, run_id="e5o", container_factory=factory_for(Crash()))
    fake = FakeContainer()
    state = executor.run(rb, run_id="e5o", resume=True, container_factory=factory_for(fake))
    assert state.status == RunStatus.PASSED
    assert fake.log == ["echo one", "echo two", "echo three", "echo four"]  # replay of 1-2, then 3-4
    assert [r.step_id for r in state.results] == [1, 2, 3, 4]


# --- E6 ------------------------------------------------------------------------

def test_e6_resume_unknown_run_id_is_a_clear_error_and_starts_nothing(tmp_runs_dir, monkeypatch):
    def boom(self):
        raise AssertionError("a container was started")

    monkeypatch.setattr(Container, "__enter__", boom)
    result = CliRunner().invoke(cli, ["run", "--resume", "20990101-000000-nope"])
    assert result.exit_code != 0
    assert "unknown run id" in result.output and "20990101-000000-nope" in result.output
    assert list(tmp_runs_dir.iterdir()) == []        # no new run folder


# --- E7 ------------------------------------------------------------------------

@pytest.mark.live
def test_e7_live_files_and_env_persist_between_steps(tmp_runs_dir, t7_cleanup):
    steps = [
        Step(id=1, intent="write", command="echo hello-from-step-1 > /work/data.txt && export FR_T7=kept"),
        Step(id=2, intent="read", command="cat /work/data.txt && echo $FR_T7",
             expected=Expected(output_contains="hello-from-step-1")),
        Step(id=3, intent="spec file", command="cat notes.txt", files=[FileSpec(path="notes.txt", content="from spec")],
             expected=Expected(output_contains="from spec")),
    ]
    state = executor.run(live_runbook(*steps), run_id="e7", container_factory=live_factory("e7"))
    assert state.status == RunStatus.PASSED, state.results
    assert "kept" in state.results[1].stdout


# --- E8 ------------------------------------------------------------------------

def test_e8_two_runs_in_one_second_get_distinct_run_folders(tmp_runs_dir):
    ids = {state_io.new_run_id("https://docs.example.com/x") for _ in range(5)}
    assert len(ids) == 5
    assert all((tmp_runs_dir / i).is_dir() for i in ids)


def test_e8_default_container_names_are_unique():
    names = {Container("python:3.11-slim").name for _ in range(20)}
    assert len(names) == 20 and all(n.startswith("1stRun-") for n in names)


@pytest.mark.live
def test_e8_live_two_runs_at_once(tmp_runs_dir, t7_cleanup):
    results: dict[str, object] = {}

    def go(tag):
        results[tag] = executor.run(live_runbook("sleep 3 && echo done"), container_factory=live_factory(tag))

    threads = [threading.Thread(target=go, args=(t,)) for t in ("e8a", "e8b")]
    [t.start() for t in threads]
    [t.join(timeout=300) for t in threads]
    a, b = results["e8a"], results["e8b"]
    assert a.status == b.status == RunStatus.PASSED
    assert a.run_id != b.run_id
    assert (tmp_runs_dir / a.run_id / "state.json").exists() and (tmp_runs_dir / b.run_id / "state.json").exists()


# --- E10 -----------------------------------------------------------------------

def test_e10_is_stale_rules(monkeypatch):
    dead = 2_000_000_001
    assert not sandbox.is_stale(f"1stRun-run-{os.getpid()}-abcdef", "3 hours ago")   # owner alive
    assert sandbox.is_stale(f"1stRun-run-{dead}-abcdef", "2 seconds ago")            # owner gone
    assert not sandbox.is_stale("1stRun-verify-1a2b3c4d", "About a minute ago")      # young, no pid
    assert sandbox.is_stale("1stRun-verify-1a2b3c4d", "3 hours ago")                 # old, no pid


@pytest.mark.live
def test_e10_live_next_run_removes_a_container_a_crash_left_behind(tmp_runs_dir, t7_cleanup):
    stale = "1stRun-t7-stale-2000000001-abcdef"        # the owner process 2000000001 does not exist
    made = _docker("run", "-d", "--name", stale, "python:3.11-slim", "sleep", "infinity")
    assert made.returncode == 0, made.stderr
    state = executor.run(live_runbook("echo hi"), run_id="e10", container_factory=live_factory("e10"))
    assert state.status == RunStatus.PASSED
    left = _docker("ps", "-a", "--filter", f"name={stale}", "--format", "{{.Names}}")
    assert stale not in left.stdout.decode()
