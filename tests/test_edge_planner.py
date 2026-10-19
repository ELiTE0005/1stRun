"""Edge cases P1-P7 (planner), E9 (Windows paths), K1, K2, K5 (docs and model failures)."""

from __future__ import annotations

import json
import subprocess

import httpx
import pytest
from click.testing import CliRunner

from _edge_fakes import FakeContainer, factory_for, install_recorder, make_runbook
from firstrun import executor, llm, planner
from firstrun import state as state_io
from firstrun.cli import cli
from firstrun.models import RunStatus, StepStatus
from firstrun.sandbox import Container

GOOD_STEP = {"id": 1, "intent": "install", "command": "pip install x", "files": [],
             "expected": {"exit_code": 0}, "source_line": "pip install x"}


@pytest.fixture
def no_container(monkeypatch):
    """Any attempt to start a container fails the test."""
    def boom(self):
        raise AssertionError("a container was started")
    monkeypatch.setattr(Container, "__enter__", boom)


@pytest.fixture
def online(monkeypatch):
    monkeypatch.delenv("FIRSTRUN_OFFLINE", raising=False)
    # A dummy token gets past the CLI's missing-token check, so CI with no keys reaches the planner.
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "test-token")


def _invoke(*args):
    return CliRunner().invoke(cli, list(args))


def _report(runs_dir) -> str:
    paths = list(runs_dir.glob("*/report.md"))
    assert len(paths) == 1, paths
    return paths[0].read_text(encoding="utf-8")


def _doc(tmp_path, text, name="doc.md"):
    f = tmp_path / name
    f.write_text(text, encoding="utf-8")
    return f


# --- P1 ------------------------------------------------------------------------

def test_p1_model_text_is_not_json_one_repair_retry_then_planner_failed(fake_llm):
    ask = fake_llm(["Sure! Here is the plan.", "still not json"])
    with pytest.raises(ValueError, match="planner output invalid"):
        planner.plan_from_markdown("# Doc", "u", llm=ask)
    assert len(ask.calls) == 2                     # the first try plus exactly one repair retry
    assert "invalid" in ask.calls[1]               # the retry tells the model what was wrong


def test_p1_run_report_says_planner_failed(tmp_runs_dir, tmp_path, monkeypatch, online, no_container):
    monkeypatch.setattr(planner, "ask_claude", lambda prompt, system: ("not json at all", {}))
    doc = _doc(tmp_path, "# D\n\n```bash\npip install x\n```\n")
    result = _invoke("run", str(doc))
    assert result.exit_code == 2
    assert "planner failed" in _report(tmp_runs_dir)


# --- P2 ------------------------------------------------------------------------

def test_p2_missing_field_error_names_the_field(fake_llm):
    bad = {"title": "t", "steps": [{"id": 1, "intent": "install"}]}  # no command
    ask = fake_llm([json.dumps(bad), json.dumps(bad)])
    with pytest.raises(ValueError) as err:
        planner.plan_from_markdown("# Doc", "u", llm=ask)
    assert "command" in str(err.value)
    assert "command" in ask.calls[1]               # the repair prompt names the field too


# --- P3 ------------------------------------------------------------------------

def test_p3_zero_commands_no_runnable_steps_exit_2_no_container(tmp_runs_dir, tmp_path, no_container):
    doc = _doc(tmp_path, "# Concepts\n\nThis page explains ideas. There is nothing to run.\n")
    result = _invoke("run", str(doc), "--offline")
    assert result.exit_code == 2
    assert "no runnable steps" in _report(tmp_runs_dir)


# --- P4 ------------------------------------------------------------------------

def test_p4_more_than_ten_steps_is_out_of_scope(tmp_runs_dir, tmp_path, no_container):
    lines = "\n".join(f"echo step{i}" for i in range(11))
    doc = _doc(tmp_path, f"# Long\n\n```bash\n{lines}\n```\n")
    result = _invoke("run", str(doc), "--offline")
    assert result.exit_code == 2
    assert "out of scope: more than 10 steps" in _report(tmp_runs_dir)


def test_p4_ten_steps_is_allowed(tmp_path, monkeypatch):
    monkeypatch.setenv("FIRSTRUN_OFFLINE", "1")
    lines = "\n".join(f"echo step{i}" for i in range(10))
    doc = _doc(tmp_path, f"# Ten\n\n```bash\n{lines}\n```\n")
    assert len(planner.plan(str(doc)).steps) == 10


# --- P5 ------------------------------------------------------------------------

SKIP_DOC = "# Doc\n\n```bash\npip install x\n```\n"


def _skipped_plan():
    skipped = {"id": 2, "intent": "create a paid account", "command": "open https://example.com/pricing",
               "skipped_out_of_scope": True, "skip_reason": "needs a paid account"}
    return {"title": "t", "steps": [GOOD_STEP, skipped]}


def test_p5_paid_account_step_is_marked_skipped_with_a_reason(fake_llm):
    rb = planner.plan_from_markdown(SKIP_DOC, "u", llm=fake_llm([json.dumps(_skipped_plan())]))
    assert rb.steps[1].skipped_out_of_scope is True
    assert rb.steps[1].skip_reason == "needs a paid account"
    assert rb.steps[0].skipped_out_of_scope is False


def test_p5_executor_never_runs_a_skipped_step(tmp_runs_dir, fake_llm):
    rb = planner.plan_from_markdown(SKIP_DOC, "u", llm=fake_llm([json.dumps(_skipped_plan())]))
    fake = FakeContainer()
    state = executor.run(rb, run_id="p5", container_factory=factory_for(fake))
    assert state.status == RunStatus.PASSED
    assert fake.log == ["pip install x"]
    assert state.step_status[2] == StepStatus.SKIPPED


def test_p5_only_skipped_steps_means_no_runnable_steps(fake_llm):
    only = {"title": "t", "steps": [dict(_skipped_plan()["steps"][1], id=1)]}
    rb = planner.plan_from_markdown("# Doc", "u", llm=fake_llm([json.dumps(only)]))
    with pytest.raises(planner.PlanError, match="no runnable steps"):
        planner.check_scope(rb)


# --- P6 ------------------------------------------------------------------------

def _unreachable(monkeypatch, status):
    def firecrawl(url):
        raise RuntimeError("firecrawl failed: Insufficient credits or blocked")

    request = httpx.Request("GET", "https://docs.example.com/q")
    monkeypatch.setattr(planner, "_firecrawl_scrape", firecrawl)
    monkeypatch.setattr(httpx, "get", lambda *a, **k: httpx.Response(status, request=request, text="nope"))


@pytest.mark.parametrize("status", [404, 403])
def test_p6_unreachable_docs_error_names_firecrawl_in_the_span(monkeypatch, status):
    rec = install_recorder(monkeypatch)
    _unreachable(monkeypatch, status)
    with pytest.raises(planner.DocsUnreachable, match="docs unreachable"):
        planner.read_docs("https://docs.example.com/q")
    assert "firecrawl failed" in rec.log_text()


def test_p6_run_report_says_docs_unreachable(tmp_runs_dir, monkeypatch, online, no_container):
    _unreachable(monkeypatch, 404)
    result = _invoke("run", "https://docs.example.com/q")
    assert result.exit_code == 2
    assert "docs unreachable" in _report(tmp_runs_dir)


# --- P7 ------------------------------------------------------------------------

BANNER_PHRASES = ("Wayback Machine", "395 captures", "Close the toolbar", "Share via My Web Archive")


def test_p7_wayback_banner_is_removed_before_planning(fixtures_dir, fake_llm):
    markdown = (fixtures_dir / "docs" / "openai_v0_FIXTURE.md").read_text(encoding="utf-8")
    assert all(p in markdown for p in BANNER_PHRASES)          # the fixture really carries the banner
    ask = fake_llm([json.dumps({"title": "t", "steps": [GOOD_STEP]})])
    planner.plan_from_markdown(markdown, "u", llm=ask)
    prompt = ask.calls[0]
    assert not any(p in prompt for p in BANNER_PHRASES)
    assert "pip install --upgrade openai" in prompt            # the commands stay


def test_p7_heuristic_keeps_commands_and_ignores_banner(tmp_path):
    md = ("[395 captures](https://web.archive.org/x \"See a list of every capture\")\n\n"
          "[Close the toolbar](https://web.archive.org/y)\n\n```bash\npip install openai\n```\n")
    rb = planner.heuristic_plan(md, "u")
    assert [s.command for s in rb.steps] == ["pip install openai"]


# --- E9 ------------------------------------------------------------------------

def test_e9_windows_paths_become_linux_paths_and_nothing_else_changes():
    cmd = r'python C:\Users\me\app\main.py --config .\conf\a.yaml --msg "a\nb"'
    out = planner.posix_paths(cmd)
    assert out == 'python /work/Users/me/app/main.py --config ./conf/a.yaml --msg "a\\nb"'
    assert "C:" not in out
    untouched = r"pip install 'x[y]' && echo a \
 b"
    assert planner.posix_paths(untouched) == untouched


def test_e9_planner_rewrites_commands_before_the_container_sees_them(fake_llm):
    step = dict(GOOD_STEP, command=r"python C:\proj\run.py")
    doc = "# D\n\n```bash\npython C:\\proj\\run.py\n```\n"
    rb = planner.plan_from_markdown(doc, "u", llm=fake_llm([json.dumps({"title": "t", "steps": [step]})]))
    assert rb.steps[0].command == "python /work/proj/run.py"
    assert rb.steps[0].source_line == "pip install x"          # the docs line is not rewritten


# --- K1 ------------------------------------------------------------------------

def test_k1_insufficient_credits_activates_a_key_and_retries_once(monkeypatch, tmp_path):
    keys = tmp_path / "keys.py"
    keys.write_text("# stand-in", encoding="utf-8")
    monkeypatch.setattr(planner, "KEYS_SCRIPT", str(keys))
    calls = {"scrape": 0, "activate": 0}

    def scrape(exe, url):
        calls["scrape"] += 1
        if calls["scrape"] == 1:
            return subprocess.CompletedProcess([], 1, stdout="", stderr="Insufficient credits")
        return subprocess.CompletedProcess([], 0, stdout="# docs", stderr="")

    def run(cmd, **kw):
        assert cmd[-1] == "activate"
        calls["activate"] += 1
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(planner.shutil, "which", lambda name: "firecrawl")
    monkeypatch.setattr(planner, "_run_firecrawl", scrape)
    monkeypatch.setattr(planner.subprocess, "run", run)
    assert planner._firecrawl_scrape("https://docs.example.com") == "# docs"
    assert calls == {"scrape": 2, "activate": 1}


# --- K2 ------------------------------------------------------------------------

def test_k2_expired_token_stops_the_run_with_model_auth_failed(monkeypatch):
    async def expired(**kwargs):
        raise Exception("OAuth token has expired. Please run /login")
        yield  # pragma: no cover

    monkeypatch.setattr(llm.sdk, "query", expired)
    with pytest.raises(llm.ModelAuthError, match="model auth failed"):
        llm.ask("hi")


def test_k2_run_report_says_model_auth_failed(tmp_runs_dir, tmp_path, monkeypatch, online, no_container):
    def expired(prompt, system):
        raise llm.ModelAuthError("model auth failed: token expired")

    monkeypatch.setattr(planner, "ask_claude", expired)
    doc = _doc(tmp_path, "# D\n\n```bash\npip install x\n```\n")
    result = _invoke("run", str(doc))
    assert result.exit_code == 2
    assert "model auth failed" in _report(tmp_runs_dir)


# --- K5 ------------------------------------------------------------------------

def test_k5_saved_fixture_is_labeled_a_fixture_in_the_report(tmp_runs_dir, fixtures_dir):
    from firstrun import report

    source = (fixtures_dir / "docs" / "openai_v0_FIXTURE.md").as_uri()
    rb = make_runbook("echo hi", source_url=source)
    state = executor.run(rb, run_id="k5", container_factory=factory_for(FakeContainer()))
    text = report.write_report(state, rb).read_text(encoding="utf-8")
    assert "fixture" in text.lower()
    assert state_io.load_state("k5").source_url == source


def test_k5_wayback_url_is_labeled_too():
    from firstrun import report

    assert report.is_fixture("https://web.archive.org/web/20230802050711/https://github.com/openai/openai-python")
    assert not report.is_fixture("https://docs.neatlogs.com/sdk/python")
