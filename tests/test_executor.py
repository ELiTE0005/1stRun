"""Track T2 tests. Offline tests use a FakeContainer. Live tests need Docker in WSL."""

from __future__ import annotations

import json

import pytest

from onestrun import config, executor, report, state as state_io
from onestrun.models import (
    Budget, Expected, FileSpec, GaveUp, Patch, Runbook, RunStatus, Step, StepResult, StepStatus,
)
from onestrun.sandbox import Container


class FakeContainer:
    """Scripted container: maps a command to (exit_code, stdout, stderr). Records every exec."""

    def __init__(self, script=None, crash_on=None, files=()):
        self.script = script or {}
        self.crash_on = crash_on
        self.log: list[str] = []
        self.files = set(files)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def write_files(self, files):
        for f in files:
            self.files.add(f.path)

    def exec(self, command, timeout_s=300):
        self.log.append(command)
        if command == self.crash_on:
            raise KeyboardInterrupt()
        if command.startswith("test -e "):
            # The real check tries several folders; the fake only needs the path itself.
            path = command.split()[2].strip("'")
            return StepResult(step_id=0, command=command, exit_code=0 if path in self.files else 1)
        code, out, err = self.script.get(command, (0, "", ""))
        return StepResult(step_id=0, command=command, exit_code=code, stdout=out, stderr=err, duration_s=0.01)


def make_runbook(*commands, **kw) -> Runbook:
    steps = [Step(id=i, intent=f"step {i}", command=c) for i, c in enumerate(commands, 1)]
    return Runbook(source_url="https://docs.example.com/quickstart", title="Example", steps=steps, **kw)


@pytest.fixture(autouse=True)
def runs(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path)
    return tmp_path


def factory_for(container):
    return lambda image=None, **kw: container


def test_check_expected():
    step = Step(id=1, intent="x", command="x", expected=Expected(exit_code=0, output_contains="ok"))
    good = StepResult(step_id=1, command="x", exit_code=0, stdout="all ok")
    assert executor.check_expected(step, good)
    assert not executor.check_expected(step, good.model_copy(update={"stdout": "nope"}))
    assert not executor.check_expected(step, good.model_copy(update={"exit_code": 2}))
    assert not executor.check_expected(step, good.model_copy(update={"timed_out": True}))


def test_check_expected_file_exists():
    step = Step(id=1, intent="x", command="x", expected=Expected(file_exists="a.txt"))
    res = StepResult(step_id=1, command="x", exit_code=0)
    assert executor.check_expected(step, res, FakeContainer(files={"a.txt"}))
    assert not executor.check_expected(step, res, FakeContainer())
    assert not executor.check_expected(step, res)


def test_run_all_pass_writes_state_after_every_step(runs, monkeypatch):
    saved = []
    real = state_io.save_state

    def spy(st):
        saved.append(st.last_good_step)
        return real(st)

    monkeypatch.setattr(state_io, "save_state", spy)
    rb = make_runbook("echo a", "echo b", "echo c")
    st = executor.run(rb, run_id="r1", container_factory=factory_for(FakeContainer()))
    assert st.status == RunStatus.PASSED
    assert st.last_good_step == 3
    assert st.time_to_first_success_s is not None
    assert {0, 1, 2, 3} <= set(saved)
    assert (runs / "r1" / "runbook.json").exists()
    assert (runs / "r1" / "report.md").exists()
    assert state_io.load_state("r1").status == RunStatus.PASSED


def test_failure_stops_run_without_recovery(runs):
    fake = FakeContainer({"bad": (2, "", "boom: no such file\nlast line")})
    st = executor.run(make_runbook("ok", "bad", "never"), run_id="r2", container_factory=factory_for(fake))
    assert st.status == RunStatus.FAILED
    assert st.first_failed_step == 2
    assert st.last_good_step == 1
    assert "never" not in fake.log
    assert st.step_status[3] == StepStatus.PENDING
    text = (runs / "r2" / "report.md").read_text(encoding="utf-8")
    assert "fail" in text and "`bad`" in text and "Exit code: 2" in text and "last line" in text


def test_recover_patch_path(runs):
    fake = FakeContainer({"pip instal x": (1, "", "ERROR: unknown command")})
    seen = []

    def recover(step, result, state, docs):
        seen.append((step.command, result.exit_code, docs))
        return Patch(step_id=step.id, old_command=step.command, new_command="echo fixed", reason="typo")

    rb = make_runbook("pip instal x", "echo done", docs_markdown="DOCS")
    st = executor.run(rb, run_id="r3", recover=recover, container_factory=factory_for(fake))
    assert st.status == RunStatus.PASSED
    assert st.attempts[1] == 2
    assert st.patches[0].new_command == "echo fixed"
    assert st.first_failed_step == 1
    assert seen == [("pip instal x", 1, "DOCS")]
    assert fake.log == ["pip instal x", "echo fixed", "echo done"]
    assert "echo fixed" in (runs / "r3" / "report.md").read_text(encoding="utf-8")


def test_recover_gave_up(runs):
    fake = FakeContainer({"bad": (1, "", "x")})
    st = executor.run(
        make_runbook("bad", "after"), run_id="r4",
        recover=lambda s, r, state, d: GaveUp(step_id=s.id, reason="needs a secret"),
        container_factory=factory_for(fake),
    )
    assert st.status == RunStatus.FAILED
    assert st.step_status[1] == StepStatus.GAVE_UP
    assert st.gave_up[0].reason == "needs a secret"
    assert "after" not in fake.log


def test_attempt_budget(runs):
    fake = FakeContainer({"bad": (1, "", "x")})
    calls = []

    def recover(step, result, state, docs):
        calls.append(1)
        return Patch(step_id=step.id, old_command=step.command, new_command="bad", reason="again")

    st = executor.run(make_runbook("bad"), run_id="r5", recover=recover,
                      budget=Budget(attempts_per_step=3), container_factory=factory_for(fake))
    assert st.status == RunStatus.FAILED
    assert st.attempts[1] == 3
    assert len(calls) == 2


def test_resume_after_crash_replays_passed_steps(runs):
    rb = make_runbook("one", "two", "three", "four")
    first = FakeContainer(crash_on="three")
    with pytest.raises(KeyboardInterrupt):
        executor.run(rb, run_id="r6", container_factory=factory_for(first))
    crashed = state_io.load_state("r6")
    assert crashed.last_good_step == 2
    assert crashed.status == RunStatus.FAILED and crashed.stop_reason == "interrupted"

    second = FakeContainer()
    st = executor.run(rb, run_id="r6", resume=True, container_factory=factory_for(second))
    assert second.log == ["one", "two", "three", "four"]  # 1 and 2 replay, then 3 and 4 run
    assert st.status == RunStatus.PASSED
    assert [r.step_id for r in st.results] == [1, 2, 3, 4]  # replays are not re-recorded


def test_resume_replays_patched_command(runs):
    fake = FakeContainer({"bad": (1, "", "x")})
    rb = make_runbook("bad", "boom")
    fake.script["boom"] = (1, "", "x")

    def recover(step, result, state, docs):
        return Patch(step_id=1, old_command="bad", new_command="good", reason="r")

    executor.run(rb, run_id="r7", recover=recover, container_factory=factory_for(fake))  # step 2 fails
    second = FakeContainer()
    executor.run(rb, run_id="r7", resume=True, container_factory=factory_for(second))
    assert second.log[0] == "good"


def test_step_files_written(runs):
    fake = FakeContainer()
    step = Step(id=1, intent="x", command="python app.py", files=[FileSpec(path="app.py", content="print(1)")],
                expected=Expected(file_exists="app.py"))
    rb = Runbook(source_url="https://x.dev/start", steps=[step])
    st = executor.run(rb, run_id="r8", container_factory=factory_for(fake))
    assert st.status == RunStatus.PASSED
    assert "app.py" in fake.files


def test_summary_table_and_state_helpers(runs):
    executor.run(make_runbook("ok"), run_id="r9", container_factory=factory_for(FakeContainer()))
    table = report.summary_table(runs)
    assert "r9" in table and "docs.example.com" in table and "1/1" in table
    assert state_io.target_name("https://www.neatlogs.com/docs") == "neatlogs.com"
    assert state_io.new_run_id("https://docs.example.com/x").endswith("-docs-example-com")
    json.loads((runs / "r9" / "state.json").read_text(encoding="utf-8"))


# --- live: needs Docker in WSL ---------------------------------------------

@pytest.mark.live
def test_live_two_step_runbook(runs):
    rb = make_runbook("echo hello", 'python -c "print(1+1)"')
    rb.steps[0].expected = Expected(output_contains="hello")
    rb.steps[1].expected = Expected(output_contains="2")
    st = executor.run(
        rb, run_id="live1",
        container_factory=lambda image=None, **kw: Container(image or "python:3.11-slim", name="1stRun-t2-live1"),
    )
    assert st.status == RunStatus.PASSED, st.results


@pytest.mark.live
def test_live_state_persists_and_timeout_and_files():
    with Container(name="1stRun-t2-state") as c:
        c.write_files([FileSpec(path="sub/dir/a.txt", content="hi there")])
        assert c.exec("mkdir -p proj && cd proj && export FOO='a b'").exit_code == 0
        r = c.exec("pwd; echo $FOO; cat ../sub/dir/a.txt 2>/dev/null || cat /work/sub/dir/a.txt")
        assert "/work/proj" in r.stdout and "a b" in r.stdout and "hi there" in r.stdout
        assert c.exec("exit 7").exit_code == 7
        assert c.exec("echo é").stdout.strip() == "é"
        t = c.exec("sleep 30", timeout_s=3)
        assert t.timed_out and t.exit_code == 124
        assert c.exec("echo alive").stdout.strip() == "alive"  # the killed sleep did not wedge the box
        big = c.exec("head -c 100000 /dev/zero | tr '\\0' x")
        assert len(big.stdout) <= 20 * 1024


@pytest.mark.live
def test_live_crash_and_resume(runs):
    rb = make_runbook("mkdir -p /work/p && cd /work/p && echo one > f.txt", "cat f.txt", "echo three")
    rb.steps[1].expected = Expected(output_contains="one")
    mk = lambda tag: (lambda image=None, **kw: Container(image or "python:3.11-slim", name=f"1stRun-t2-resume-{tag}"))

    class Boom(Container):
        def exec(self, command, timeout_s=300):
            if command == "echo three":
                raise KeyboardInterrupt()
            return super().exec(command, timeout_s)

    with pytest.raises(KeyboardInterrupt):
        executor.run(rb, run_id="live2", container_factory=lambda image=None, **kw: Boom(image, name="1stRun-t2-resume-a"))
    assert state_io.load_state("live2").last_good_step == 2
    st = executor.run(rb, run_id="live2", resume=True, container_factory=mk("b"))
    assert st.status == RunStatus.PASSED


def test_dev_server_step_passes_once_it_is_listening():
    from onestrun import executor
    from onestrun.models import Step, StepResult

    assert executor.is_server_command("pip install flask && flask --app hello run")
    assert executor.is_server_command("uvicorn main:app --reload")
    assert executor.is_server_command("python manage.py runserver")
    assert not executor.is_server_command("pip install flask")
    up = StepResult(step_id=1, command="flask run", exit_code=124, timed_out=True,
                    stderr=" * Running on http://127.0.0.1:5000\nPress CTRL+C to quit")
    up.server_ready = executor.server_ready(up)
    assert up.server_ready and executor.check_expected(Step(id=1, intent="run", command="flask run"), up)
    hung = StepResult(step_id=1, command="flask run", exit_code=124, timed_out=True, stderr="Traceback")
    hung.server_ready = executor.server_ready(hung)
    assert not hung.server_ready and not executor.check_expected(Step(id=1, intent="run", command="flask run"), hung)


def test_install_step_naming_a_server_package_keeps_the_full_timeout():
    from onestrun import executor

    # The server name is a package here, so the 90 s server window must not cap a slow install.
    assert not executor.is_server_command("pip install fastapi uvicorn")
    assert not executor.is_server_command("pip install gunicorn")
    assert not executor.is_server_command("npm install vite --save-dev")
    assert not executor.is_server_command("uv add 'uvicorn[standard]'")
    assert executor.is_server_command("pip install uvicorn && uvicorn main:app")
    assert executor.is_server_command("npm install; npm run dev")
