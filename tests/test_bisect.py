"""Docs Bisect. Offline: fake PyPI JSON, fake containers, no Docker, no model."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from firstrun import bisect as bisect_mod, config, state as state_io
from firstrun.cli import cli
from firstrun.models import FileSpec, Patch, Runbook, RunState, RunStatus, Step, StepResult, StepStatus


def _file(date: str, requires: str | None = None, yanked: bool = False) -> dict:
    return {"upload_time_iso_8601": f"{date}T10:00:00.000000Z", "requires_python": requires, "yanked": yanked}


FAKE_PYPI = {"releases": {
    "0.1.0": [_file("2021-01-01", ">=3.12")],          # needs a newer Python
    "0.2.0": [_file("2022-01-01", ">=3.7")],
    "0.3.0": [_file("2023-02-01")],
    "0.4.0rc1": [_file("2023-06-01")],                  # pre-release
    "0.4.1.dev3": [_file("2023-06-02")],                # dev release
    "0.5.0": [_file("2023-07-01", yanked=True)],        # yanked
    "0.6.0": [],                                        # no files
    "1.0.0": [_file("2024-05-02", ">=3.8"), _file("2024-05-03")],
    "10.0.0": [_file("2025-01-01", ">=3.9,<4")],
    "bad-version": [_file("2025-02-01")],
}}


def test_releases_filters_and_sorts():
    got = bisect_mod.releases("pkg", "3.11", fetch=lambda url: FAKE_PYPI)
    assert got == [("0.2.0", "2022-01-01"), ("0.3.0", "2023-02-01"), ("1.0.0", "2024-05-02"),
                   ("10.0.0", "2025-01-01")]


def test_releases_python_floor_changes_the_list():
    got = bisect_mod.releases("pkg", "3.12", fetch=lambda url: FAKE_PYPI)
    assert got[0] == ("0.1.0", "2021-01-01")


def test_releases_asks_pypi_for_the_package():
    seen = []
    bisect_mod.releases("jafgen", fetch=lambda url: seen.append(url) or {"releases": {}})
    assert seen == ["https://pypi.org/pypi/jafgen/json"]


def make_runbook() -> Runbook:
    return Runbook(
        source_url="https://example.com/qs", image="python:3.11-slim",
        steps=[
            Step(id=1, intent="clone", command="git clone https://x/y.git"),
            Step(id=2, intent="apt", command="echo env"),
            Step(id=3, intent="install", command="python -m pip install jafgen"),
            Step(id=4, intent="config", command="true", files=[FileSpec(path="cfg/jaf.yml", content="a: 1")]),
            Step(id=5, intent="skipped", command="pip install jafgen --serve", skipped_out_of_scope=True),
            Step(id=6, intent="run", command="jafgen --years 6 --config jaf.yml"),
            Step(id=7, intent="later", command="jafgen again"),
        ],
    )


def test_slice_steps_keeps_package_file_and_failing_step_in_order():
    patches = [Patch(step_id=3, old_command="python -m pip install jafgen",
                     new_command="apt-get install -y gcc && python -m pip install jafgen", reason="env"),
               Patch(step_id=6, old_command="jafgen --years 6 --config jaf.yml",
                     new_command="jafgen 6", reason="docs")]
    out = bisect_mod.slice_steps(make_runbook(), 6, "jafgen", patches)
    assert [s.id for s in out] == [3, 4, 6]
    assert out[0].command.startswith("apt-get install")          # patched environment fix stays
    assert out[-1].command == "jafgen --years 6 --config jaf.yml"  # failing step keeps the original


def test_slice_steps_matches_normalized_package_names():
    rb = Runbook(source_url="u", steps=[
        Step(id=1, intent="i", command="pip install my_pkg"),
        Step(id=2, intent="i", command="pip install other"),
        Step(id=3, intent="r", command="my-pkg run")])
    assert [s.id for s in bisect_mod.slice_steps(rb, 3, "my-pkg")] == [1, 3]


def test_slice_steps_unknown_step():
    with pytest.raises(ValueError):
        bisect_mod.slice_steps(make_runbook(), 99, "jafgen")


# --- fake runtime --------------------------------------------------------------

class FakeContainer:
    created: list = []

    def __init__(self, image, name, env):
        self.image, self.name, self.env = image, name, env
        self.files: list[FileSpec] = []
        FakeContainer.created.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def write_files(self, files):
        self.files += files

    def pinned(self) -> str:
        return next(f.content for f in self.files if f.path == bisect_mod.CONSTRAINTS_PATH).strip()


def fake_steps(first_bad: int, versions: list[str]):
    """run_step fake: the last-step command fails when the pinned version index is >= first_bad."""
    def run_step(container, step):
        version = container.pinned().split("==")[1]
        ok = not (step.command.startswith("jafgen --years") and versions.index(version) >= first_bad)
        return StepResult(step_id=step.id, command=step.command, exit_code=0 if ok else 2,
                          stderr="" if ok else "Usage: jafgen\nError: No such option: --years", passed=ok)
    return run_step


@pytest.fixture
def fake_run(tmp_runs_dir):
    FakeContainer.created = []
    run_id = "20261010-000000-fake"
    rb = Runbook(source_url="https://example.com/qs", image="python:3.11-slim", steps=[
        Step(id=1, intent="install", command="python -m pip install jafgen"),
        Step(id=2, intent="gen", command="jafgen --years 6")])
    state_io.run_dir(run_id).mkdir(parents=True)
    state_io.save_runbook(run_id, rb)
    state = RunState(run_id=run_id, source_url=rb.source_url, status=RunStatus.VERIFIED,
                     step_status={1: StepStatus.PASSED, 2: StepStatus.GAVE_UP}, first_failed_step=2)
    state_io.save_state(state)
    return run_id


def releases_list(n: int) -> list[tuple[str, str]]:
    return [(f"0.{i}.0", f"2023-01-{i + 1:02d}") for i in range(n)]


def run_fake(run_id, rels, first_bad, **kw):
    versions = [v for v, _ in rels]
    return bisect_mod.run(run_id, "jafgen", container_factory=FakeContainer, release_list=rels,
                          run_step=fake_steps(first_bad, versions), **kw)


def test_probe_pins_release_and_names_container(fake_run):
    rb = state_io.load_runbook(fake_run)
    ok, err = bisect_mod.probe(rb.steps, rb.image, "jafgen", "0.3.0", FakeContainer,
                               fake_steps(0, ["0.3.0"]))
    c = FakeContainer.created[-1]
    assert not ok and "No such option: --years" in err
    assert c.name == "firstrun-bisect-jafgen-0.3.0"
    assert c.pinned() == "jafgen==0.3.0"
    assert c.env["PIP_CONSTRAINT"] == "/tmp/constraints.txt"


def test_probe_reports_an_earlier_step_failure(fake_run):
    rb = state_io.load_runbook(fake_run)

    def run_step(container, step):
        return StepResult(step_id=step.id, command=step.command, exit_code=1, stderr="boom", passed=False)

    ok, err = bisect_mod.probe(rb.steps, rb.image, "jafgen", "1.0.0", FakeContainer, run_step)
    assert not ok and err == "step 1: boom"


def test_probe_container_error_is_a_failed_probe(fake_run):
    rb = state_io.load_runbook(fake_run)

    def broken(image, name, env):
        raise RuntimeError("docker pull failed")

    ok, err = bisect_mod.probe(rb.steps, rb.image, "jafgen", "1.0.0", broken)
    assert not ok and "docker pull failed" in err


def test_bisect_finds_first_bad_in_log_probes(fake_run):
    rels = releases_list(10)
    doc = run_fake(fake_run, rels, first_bad=6)
    assert doc["first_bad"] == "0.6.0" and doc["last_good"] == "0.5.0"
    assert doc["first_bad_date"] == "2023-01-07"
    assert doc["probes"] <= 6  # 2 ends + ceil(log2(8))
    assert doc["step_id"] == 2 and doc["command"] == "jafgen --years 6"
    assert doc["verdict"].startswith("first bad release: jafgen 0.6.0")
    # the first two probes are the newest and the oldest release
    assert [e["version"] for e in doc["releases_tested"][:2]] == ["0.9.0", "0.0.0"]


@pytest.mark.parametrize("first_bad", [1, 9])
def test_bisect_edges(fake_run, first_bad):
    doc = run_fake(fake_run, releases_list(10), first_bad=first_bad)
    assert doc["first_bad"] == f"0.{first_bad}.0"
    assert doc["last_good"] == f"0.{first_bad - 1}.0"


def test_bisect_both_fail_is_not_a_regression(fake_run):
    doc = run_fake(fake_run, releases_list(10), first_bad=0)
    assert doc["first_bad"] is None and doc["probes"] == 2
    assert doc["verdict"] == "fails on every release: not a version regression"


def test_bisect_both_pass(fake_run):
    doc = run_fake(fake_run, releases_list(10), first_bad=99)
    assert doc["first_bad"] is None and doc["probes"] == 2
    assert doc["verdict"] == "passes on every release: no regression to find"


def test_bisect_respects_max_probes(fake_run):
    doc = run_fake(fake_run, releases_list(100), first_bad=50, max_probes=4)
    assert doc["probes"] == 4 and doc["first_bad"] is None
    assert doc["verdict"].startswith("max probes reached")
    assert doc["last_good"] is not None


def test_bisect_json_is_written_after_every_probe(fake_run):
    snapshots = []

    def on_probe(entry):
        saved = json.loads(bisect_mod.bisect_path(fake_run).read_text(encoding="utf-8"))
        snapshots.append((len(saved["releases_tested"]), saved["probes"], saved["verdict"]))

    doc = run_fake(fake_run, releases_list(10), first_bad=6, on_probe=on_probe)
    assert [s[0] for s in snapshots] == list(range(1, doc["probes"] + 1))
    assert all(s[2] == "" for s in snapshots)  # unfinished until the end
    final = json.loads(bisect_mod.bisect_path(fake_run).read_text(encoding="utf-8"))
    for key in ("package", "step_id", "command", "releases_tested", "last_good", "first_bad",
                "first_bad_date", "verdict", "probes", "started_at", "finished_at"):
        assert key in final
    assert final["finished_at"] and final["package"] == "jafgen"
    assert set(final["releases_tested"][0]) == {"version", "date", "passed", "error"}


def test_bisect_defaults_to_reported_failed_step(fake_run):
    doc = run_fake(fake_run, releases_list(4), first_bad=2)
    assert doc["step_id"] == 2


def test_bisect_uses_python_from_image(fake_run, monkeypatch):
    seen = {}
    monkeypatch.setattr(bisect_mod, "releases", lambda pkg, py: seen.update(py=py) or releases_list(3))
    bisect_mod.run(fake_run, "jafgen", container_factory=FakeContainer, run_step=fake_steps(1, [v for v, _ in releases_list(3)]))
    assert seen["py"] == "3.11"


def test_cli_prints_probe_lines_and_verdict(fake_run, monkeypatch):
    rels = [("0.3.0", "2023-02-01"), ("0.4.0", "2023-03-01"), ("0.4.11", "2023-04-01"), ("1.0.0", "2024-05-02")]
    versions = [v for v, _ in rels]
    real_run = bisect_mod.run

    def patched_run(run_id, package, step_id=None, max_probes=8, **kw):
        return real_run(run_id, package, step_id, max_probes, container_factory=FakeContainer,
                        run_step=fake_steps(3, versions), release_list=rels, **kw)

    monkeypatch.setattr(bisect_mod, "run", patched_run)
    result = CliRunner().invoke(cli, ["bisect", fake_run, "--package", "jafgen", "--step", "2"])
    assert result.exit_code == 0, result.output
    out = result.output
    assert "✗ 1.0.0" in out and "2024-05-02" in out and "No such option: --years" in out
    assert "✓ 0.3.0" in out and "2023-02-01" in out
    assert "First bad: jafgen 1.0.0 (2024-05-02). Last good: 0.4.11. 4 probes, $0 model cost." in out


def test_cli_bisect_is_a_command_not_a_url(tmp_runs_dir):
    result = CliRunner().invoke(cli, ["bisect", "nope", "--package", "x"])
    assert "unknown run id: nope" in result.output
    assert "Usage: cli run" not in result.output


def test_share_payload_carries_bisect_block(fake_run):
    from firstrun import share

    run_fake(fake_run, releases_list(6), first_bad=3)
    payload = share.build_payload(state_io.run_dir(fake_run))
    assert payload["v"] == 1 and payload["bisect"]["first_bad"] == "0.3.0"


def test_bisect_source_imports_no_model_module():
    tree = ast.parse(Path(bisect_mod.__file__).read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
            names |= {f"{node.module}.{a.name}" for a in node.names}
    for banned in ("planner", "recovery", "llm", "classify", "claude_agent_sdk", "anthropic"):
        assert not any(banned in n for n in names), banned


def test_model_calls_are_blocked_inside_a_probe(fake_run):
    rb = state_io.load_runbook(fake_run)

    def run_step(container, step):
        config.assert_model_call_allowed("claude")
        return StepResult(step_id=step.id, command=step.command, exit_code=0, passed=True)

    ok, err = bisect_mod.probe(rb.steps, rb.image, "jafgen", "1.0.0", FakeContainer, run_step)
    assert not ok and "model call blocked" in err


def test_error_line_skips_rich_box_borders():
    boxed = ("Usage: jafgen [OPTIONS] [YEARS]\n"
             "╭─ Error ─────╮\n"
             "│ No such option: --years │\n"
             "╰──────────────╯\n")
    res = StepResult(step_id=1, command="c", exit_code=2, stderr=boxed)
    assert bisect_mod._error_line(res) == "No such option: --years"
