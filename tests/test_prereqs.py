"""Prerequisite Proof: derive, markdown, prove with a fake container. No Docker, no model."""

from __future__ import annotations

import json

import pytest

from onestrun import config, prereqs
from onestrun.models import FailureClass, GaveUp, Patch, Runbook, RunState, RunStatus, Step, StepResult


def _res(sid, cmd, code=0, err="", out=""):
    return StepResult(step_id=sid, command=cmd, exit_code=code, stderr=err, stdout=out, passed=code == 0)


def _rb(*cmds, image="python:3.11-slim"):
    return Runbook(source_url="https://x.test/d", title="the Acme quickstart", image=image,
                   steps=[Step(id=i + 1, intent="i", command=c) for i, c in enumerate(cmds)])


def _state(**kw):
    return RunState(run_id="r1", source_url="https://x.test/d", status=RunStatus.VERIFIED, **kw)


def test_apt_install_multi_package_and_flags():
    cmd = "apt-get update -qq && apt-get install -y -qq --no-install-recommends curl ca-certificates gnupg && echo ok"
    rb = _rb("curl x | sh")
    st = _state(results=[_res(1, "curl x | sh", 127, "/tmp/.fr_step.sh: line 6: curl: command not found")],
                patches=[Patch(step_id=1, old_command="curl x | sh", new_command=cmd, reason="r",
                               failure_class=FailureClass.ENVIRONMENT)])
    d = prereqs.derive(st, rb)
    assert d["system_packages"] == ["curl", "ca-certificates", "gnupg"]
    assert d["tools"] == ["curl"]
    ev = next(e for e in d["evidence"] if e["item"] == "curl")
    assert ev["step_id"] == 1 and ev["error_line"] == "curl: command not found"


def test_install_in_original_command_is_not_a_prerequisite():
    rb = _rb("sudo apt install knoxctl")
    st = _state(patches=[Patch(step_id=1, old_command="sudo apt install knoxctl",
                               new_command="apt-get update && apt-get install -y knoxctl", reason="r",
                               failure_class=FailureClass.ENVIRONMENT)])
    assert prereqs.derive(st, rb)["system_packages"] == []


def test_sudo_missing_is_a_tool():
    rb = _rb("sudo apt update")
    st = _state(results=[_res(1, "sudo apt update", 127, "/tmp/.fr_step.sh: line 6: sudo: command not found")])
    d = prereqs.derive(st, rb)
    assert d["tools"] == ["sudo"]
    assert prereqs.install_set(d) == ["sudo"]


def test_path_export():
    rb = _rb("entire version")
    st = _state(patches=[Patch(step_id=1, old_command="entire version",
                               new_command='export PATH="$HOME/.local/bin:$PATH" && entire version',
                               reason="r", failure_class=FailureClass.DOCS_BUG)])
    assert prereqs.derive(st, rb)["path"] == ["$HOME/.local/bin"]


PIP_ERR = ("ERROR: Could not find a version that satisfies the requirement networkx==3.7 "
           "(from versions: 3.5, 3.6.1)\nNote: 3.7 Requires-Python >=3.12,!=3.14.1; 3.7rc0 Requires-Python >=3.12\n"
           "ERROR: No matching distribution found for networkx==3.7")


def test_python_floor_from_pip_error_without_network():
    def no_net(name, version):
        raise AssertionError("the floor pip printed must win over a lookup")

    rb = _rb("python3 -m pip install -r requirements.txt")
    st = _state(results=[_res(1, rb.steps[0].command, 1, PIP_ERR)])
    d = prereqs.derive(st, rb, fetch=no_net)
    assert d["python"] == ">=3.12"
    assert next(e for e in d["evidence"] if e["item"] == "python")["error_line"].endswith("networkx==3.7")


def test_python_floor_from_pypi_lookup_and_requires_a_different_python():
    seen = []

    def fetch(name, version):
        seen.append((name, version))
        return ">=3.10"

    rb = _rb("pip install foo==1.2")
    st = _state(results=[_res(1, "pip install foo==1.2", 1, "ERROR: No matching distribution found for foo==1.2")])
    assert prereqs.derive(st, rb, fetch=fetch)["python"] == ">=3.10"
    assert seen == [("foo", "1.2")]
    st2 = _state(results=[_res(1, "pip install .", 1,
                               "ERROR: Package 'x' requires a different Python: 3.11.9 not in '>=3.13'")])
    assert prereqs.derive(st2, _rb("pip install ."))["python"] == ">=3.13"


def test_lookup_failure_gives_no_floor():
    def boom(name, version):
        raise OSError("offline")

    st = _state(results=[_res(1, "pip install foo==1.2", 1, "ERROR: No matching distribution found for foo==1.2")])
    assert prereqs.derive(st, _rb("pip install foo==1.2"), fetch=boom)["python"] is None


def test_secrets_names_only():
    rb = _rb("acme login")
    st = _state(gave_up=[GaveUp(step_id=1, reason="needs ACME_API_KEY, the docs say to export it",
                                failure_class=FailureClass.NEEDS_SECRET)],
                results=[_res(1, "acme login", 1, "error: key sk-live-abc123 is invalid")])
    d = prereqs.derive(st, rb)
    assert d["secrets"] == ["ACME_API_KEY"]
    assert "sk-live" not in json.dumps(d)


def test_markdown_wording():
    d = {"system_packages": ["curl"], "python": ">=3.12", "path": ["$HOME/.local/bin"], "secrets": [], "tools": [],
         "evidence": [{"item": "curl", "step_id": 1, "command": "curl -fsSL https://e.test/i.sh | bash",
                       "error_line": "curl: command not found", "fix": "x"}]}
    md = prereqs.to_markdown(d, "the Acme quickstart")
    assert md.startswith("## Prerequisites\n")
    assert "- `curl`. Step 1 (`curl -fsSL https://e.test/i.sh | bash`) needs it. It fails with: curl: command not found." in md
    assert "- Python 3.12 or newer." in md
    assert "`$HOME/.local/bin` on your PATH." in md
    assert "—" not in md and "–" not in md
    empty = {"system_packages": [], "python": None, "path": [], "secrets": [], "tools": [], "evidence": []}
    assert "nothing beyond" in prereqs.to_markdown(empty)


# --- prove -------------------------------------------------------------------

class FakeContainer:
    def __init__(self, image, name, have, log):
        self.image, self.name, self.have, self.log = image, name, have, log

    def __enter__(self):
        self.log.append(("start", self.image, self.name))
        return self

    def __exit__(self, *a):
        return None

    def exec(self, command, timeout_s=300):
        self.log.append(("exec", command))
        if "apt-get install" in command:
            tail = command.split("install", 1)[1]
            self.have.update(t for t in tail.split() if not t.startswith("-"))
        return _res(0, command)


def _factory(log):
    return lambda image, name: FakeContainer(image, name, set(), log)


def _runner_needing(tool_by_step):
    def run(container, step):
        need = tool_by_step.get(step.id)
        if need and need not in container.have:
            return _res(step.id, step.command, 127, f"/tmp/.fr_step.sh: line 6: {need}: command not found")
        return _res(step.id, step.command, 0)

    return run


@pytest.fixture
def run_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path)
    from onestrun import state as state_io

    def make(rb, st):
        (tmp_path / "r1").mkdir()
        state_io.save_runbook("r1", rb)
        state_io.save_state(st)
        return tmp_path / "r1"

    return make


def _curl_state():
    return _state(
        results=[_res(1, "curl x | sh", 127, "/tmp/.fr_step.sh: line 6: curl: command not found")],
        patches=[Patch(step_id=1, old_command="curl x | sh", new_command="apt-get install -y curl && curl x | sh",
                       reason="r", failure_class=FailureClass.ENVIRONMENT)])


def test_prove_passes_and_writes_files(run_folder):
    rb = _rb("curl x | sh", "echo done")
    folder = run_folder(rb, _curl_state())
    log: list = []
    out = prereqs.prove("r1", container_factory=_factory(log), run_step=_runner_needing({1: "curl"}))
    assert out["proof"]["proven"] and out["proof"]["rounds"] == 1
    assert out["proof"]["steps_passed"] == out["proof"]["steps_total"] == 2
    assert log[0][0] == "start" and log[0][2].startswith("1stRun-prereq-")
    assert any("apt-get update" in e[1] and "curl" in e[1] for e in log if e[0] == "exec")
    saved = json.loads((folder / "prereqs.json").read_text(encoding="utf-8"))
    assert saved["proof"]["proven"] is True and saved["system_packages"] == ["curl"]
    assert "## Prerequisites" in (folder / "prereqs.md").read_text(encoding="utf-8")
    assert prereqs.proof_line(out) == ("Proven: a fresh python:3.11-slim container with only these "
                                       "prerequisites ran 2/2 steps as written.")


def test_prove_fails_then_round_two_adds_missing_tool(run_folder):
    rb = _rb("curl x | sh", "git clone y")
    run_folder(rb, _curl_state())
    log: list = []
    out = prereqs.prove("r1", rounds=2, container_factory=_factory(log),
                        run_step=_runner_needing({1: "curl", 2: "git"}))
    assert out["proof"]["proven"] and out["proof"]["rounds"] == 2
    assert out["proof"]["added"] == ["git"]
    assert "git" in prereqs.install_set(out)
    assert len([e for e in log if e[0] == "start"]) == 2


def test_prove_fails_honestly_when_nothing_is_named(run_folder):
    rb = _rb("curl x | sh", "bad")
    run_folder(rb, _curl_state())

    def run(container, step):
        if step.id == 2:
            return _res(2, "bad", 1, "boom: it broke")
        return _res(step.id, step.command, 0)

    out = prereqs.prove("r1", container_factory=_factory([]), run_step=run)
    p = out["proof"]
    assert not p["proven"] and p["failed_step"] == 2 and p["rounds"] == 1 and p["error"] == "boom: it broke"
    assert prereqs.proof_line(out).startswith("Not proven: step 2 failed")


def test_prove_stops_after_round_limit(run_folder):
    rb = _rb("curl x | sh", "git a", "make b")
    run_folder(rb, _curl_state())
    out = prereqs.prove("r1", rounds=2, container_factory=_factory([]),
                        run_step=_runner_needing({1: "curl", 2: "git", 3: "make"}))
    assert not out["proof"]["proven"] and out["proof"]["rounds"] == 2 and out["proof"]["failed_step"] == 3


def test_prove_uses_floor_image_and_skips_out_of_scope(run_folder):
    rb = _rb("pip install -r requirements.txt", "serve")
    rb.steps[1].skipped_out_of_scope = True
    run_folder(rb, _state(results=[_res(1, rb.steps[0].command, 1, PIP_ERR)]))
    seen: list = []

    def run(container, step):
        seen.append(step.id)
        return _res(step.id, step.command, 0)

    out = prereqs.prove("r1", container_factory=_factory([]), run_step=run)
    assert out["proof"]["image"] == "python:3.12-slim" and out["proof"]["proven"]
    assert seen == [1] and out["proof"]["steps_total"] == 1


def test_prove_runs_original_commands_with_model_calls_blocked(run_folder):
    rb = _rb("curl x | sh")
    run_folder(rb, _curl_state())
    ran: list = []

    def run(container, step):
        ran.append(step.command)
        with pytest.raises(config.ModelCallBlocked):
            config.assert_model_call_allowed("test")
        return _res(step.id, step.command, 0)

    prereqs.prove("r1", container_factory=_factory([]), run_step=run)
    assert ran == ["curl x | sh"]  # the docs command as written, not the patch
    src = open(prereqs.__file__, encoding="utf-8").read()
    for banned in ("from onestrun import planner", "from onestrun import recovery", "from onestrun import llm",
                   "onestrun.planner", "onestrun.recovery", "onestrun.llm"):
        assert f"import {banned}" not in src and f"from {banned}" not in src


def test_docs_bug_note(run_folder):
    rb = _rb("tool --years 6")
    st = _state(patches=[Patch(step_id=1, old_command="tool --years 6", new_command="tool 6", reason="r",
                               failure_class=FailureClass.DOCS_BUG)])
    run_folder(rb, st)
    out = prereqs.prove("r1", container_factory=_factory([]),
                        run_step=lambda c, s: _res(s.id, s.command, 2, "No such option: --years"))
    assert not out["proof"]["proven"] and "docs bug" in out["proof"]["note"]


def test_round_two_learns_from_go_style_exec_error(run_folder):
    rb = _rb("install.sh")
    run_folder(rb, _state())
    err = 'cannot find repo: exec: "git": executable file not found in $PATH\n`doctor` still works here.'

    def run(container, step):
        if "git" not in container.have:
            return _res(step.id, step.command, 1, err)
        return _res(step.id, step.command, 0)

    out = prereqs.prove("r1", container_factory=_factory([]), run_step=run)
    assert out["proof"]["proven"] and out["proof"]["added"] == ["git"]
    ev = next(e for e in out["evidence"] if e["item"] == "git")
    assert "executable file not found" in ev["error_line"]
    assert prereqs.proof_line({"proof": {"proven": False, "failed_step": 1, "image": "i", "rounds": 1,
                                         "error": "e"}}).startswith("Not proven: step 1 failed")
