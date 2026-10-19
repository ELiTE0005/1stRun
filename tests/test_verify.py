import ast
from pathlib import Path

import pytest

from firstrun import verify as verify_mod
from firstrun.models import Patch, Runbook, RunStatus, Step, StepResult
from firstrun.verify import apply_patches, verify, verify_details


class FakeContainer:
    def __init__(self, image, name):
        self.image, self.name = image, name

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None


def make_runbook() -> Runbook:
    return Runbook(
        source_url="https://example.com/quickstart",
        steps=[
            Step(id=1, intent="install", command="pip install foo"),
            Step(id=2, intent="run", command="python old.py"),
            Step(id=3, intent="check", command="python check.py"),
        ],
    )


def make_runner(bad: set[str], seen: list[str]):
    def run_step(container, step):
        seen.append(step.command)
        ok = step.command not in bad
        return StepResult(step_id=step.id, command=step.command, exit_code=0 if ok else 1, duration_s=0.5, passed=ok)

    return run_step


def factory_with_log(created: list):
    def factory(image, name):
        created.append((image, name))
        return FakeContainer(image, name)

    return factory


PATCH = Patch(step_id=2, old_command="python old.py", new_command="python new.py", reason="renamed")


def test_apply_patches_copies_and_last_wins():
    rb = make_runbook()
    later = Patch(step_id=2, old_command="python new.py", new_command="python newer.py", reason="x")
    out = apply_patches(rb, [PATCH, later])
    assert out.steps[1].command == "python newer.py"
    assert rb.steps[1].command == "python old.py"


def test_all_pass_is_verified():
    seen, created = [], []
    details: dict = {}
    status = verify(make_runbook(), [PATCH], factory_with_log(created), make_runner(set(), seen), out=details)
    assert status == RunStatus.VERIFIED
    assert seen == ["pip install foo", "python new.py", "python check.py"]
    assert created[0][1].startswith("firstrun-verify-")
    assert [s["passed"] for s in details["steps"]] == [True, True, True]
    assert details["steps"][0]["duration_s"] == 0.5


def test_one_failure_is_unverified_and_stops():
    seen = []
    status = verify(make_runbook(), [PATCH], factory_with_log([]), make_runner({"python new.py"}, seen))
    assert status == RunStatus.UNVERIFIED
    assert "python check.py" not in seen
    details = verify_details(make_runbook(), [], factory_with_log([]), make_runner({"python old.py"}, []))
    assert details["status"] == "unverified"
    assert details["failed_step"] == 2


def test_container_error_is_unverified():
    def boom(image, name):
        raise RuntimeError("docker down")

    assert verify(make_runbook(), [], boom, make_runner(set(), [])) == RunStatus.UNVERIFIED


def test_verify_source_imports_no_model_module():
    tree = ast.parse(Path(verify_mod.__file__).read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            names.add(base)
            names |= {f"{base}.{a.name}" for a in node.names}
    banned = ("planner", "recovery", "llm", "claude_agent_sdk", "anthropic")
    assert not [n for n in names if any(b in n.split(".") for b in banned)]


@pytest.mark.live
def test_live_verify_real_container():
    from firstrun.sandbox import Container

    try:
        Container(image="python:3.11-slim", name="firstrun-verify-probe")
    except NotImplementedError:
        pytest.skip("sandbox.Container is not implemented yet")
    rb = Runbook(source_url="https://example.com", steps=[Step(id=1, intent="echo", command="echo hi")])
    assert verify(rb, []) == RunStatus.VERIFIED
