"""Edge cases R1-R12 (recovery budget), K7 (network drop) and K8 (secret redaction). All offline."""

from __future__ import annotations

import builtins
import json

import httpx
import pytest

from _edge_fakes import FakeContainer, factory_for, install_recorder, make_runbook
from onestrun import classify, config, executor, llm, patch, precedents, recovery, sandbox
from onestrun import budget as budget_mod
from onestrun.models import GaveUp, Budget, FailureClass as FC, Patch, RunState, RunStatus, Step, StepResult, StepStatus
from onestrun.redact import MARK, redact

SECRET = "sk-ant-api03-SECRETSECRETSECRET1234"


def _probs(top, p=0.95):
    rest = (1 - p) / 3
    return {c: (p if c == top else rest) for c in FC}


@pytest.fixture(autouse=True)
def _offline(monkeypatch, tmp_precedents, tmp_path):
    monkeypatch.setattr(recovery, "_pypi_hint", lambda e: "")
    monkeypatch.setattr(config, "SECRETS_ALLOWLIST", tmp_path / "no-such-allowlist")
    monkeypatch.setattr(config, "load_env", lambda path=None: None)


def judge(monkeypatch, top, p=0.95):
    """The judge answers. Claude is down, so the judge is the one that decides."""
    monkeypatch.setattr(classify, "_claude", lambda e, c: None)
    monkeypatch.setattr(classify, "_judge", lambda e, c: _probs(top, p))


def _state():
    return RunState(run_id="r1", source_url="http://x")


def _fail(cmd="pip install chromadb==0.3", err="ERROR: No matching distribution found for chromadb==0.3"):
    return Step(id=1, intent="install", command=cmd), StepResult(step_id=1, command=cmd, exit_code=1, stderr=err)


# --- R1 ------------------------------------------------------------------------

def test_r1_same_error_three_times_gives_up_and_a_budget_span_records_it(tmp_runs_dir, monkeypatch):
    rec = install_recorder(monkeypatch)
    err = (1, "", "ERROR: No matching distribution found for chromadb==0.3")
    fake = FakeContainer({"bad": err, "bad2": err, "bad3": err})
    nxt = iter(["bad2", "bad3", "bad4"])

    def recover(step, result, state, docs):
        return Patch(step_id=step.id, old_command=step.command, new_command=next(nxt), reason="try")

    state = executor.run(make_runbook("bad"), run_id="r1", recover=recover, container_factory=factory_for(fake))
    assert state.step_status[1] == StepStatus.GAVE_UP and state.status == RunStatus.FAILED
    assert state.attempts[1] == 3
    assert "attempt budget spent" in state.gave_up[0].reason
    assert "budget" in rec.names()


# --- R2, R3 --------------------------------------------------------------------

@pytest.mark.parametrize("field,value,words", [("tool_calls", 25, "tool call budget"), ("cost_usd", 0.51, "cost budget")])
def test_r2_r3_budget_trips_stop_the_run_and_report(tmp_runs_dir, field, value, words):
    fake = FakeContainer({"bad": (1, "", "boom"), "bad2": (1, "", "boom")})

    def recover(step, result, state, docs):
        setattr(state.usage, field, value)  # the spend that the real recovery adds
        return Patch(step_id=step.id, old_command=step.command, new_command="bad2", reason="try")

    rb = make_runbook("bad", "after")
    state = executor.run(rb, run_id="r23", recover=recover, container_factory=factory_for(fake))
    assert state.status == RunStatus.FAILED and "after" not in fake.log
    assert words in state.stop_reason
    assert words in (tmp_runs_dir / "r23" / "report.md").read_text(encoding="utf-8")


def test_r2_limits_are_the_spec_values():
    assert (Budget().tool_calls_per_run, Budget().cost_usd_per_run, Budget().attempts_per_step) == (25, 0.50, 3)
    state = _state()
    state.usage.tool_calls = 24
    budget_mod.check(state, Budget(), 1)
    state.usage.tool_calls = 25
    with pytest.raises(budget_mod.BudgetExceeded):
        budget_mod.check(state, Budget(), 1)


# --- R4 ------------------------------------------------------------------------

def test_r4_claude_gives_no_answer_so_the_judge_decides_and_the_fallback_is_logged(monkeypatch):
    rec = install_recorder(monkeypatch)
    monkeypatch.setattr(classify, "_claude", lambda e, c: None)
    monkeypatch.setattr(classify, "_judge", lambda e, c: _probs(FC.DOCS_BUG, 0.8))
    cls, src = recovery.resolve_class("some error", "cmd", asker=lambda q: pytest.fail("asked"))
    assert (cls, src) == (FC.DOCS_BUG, "judge")
    assert "falling back to the local judge model" in rec.log_text()


def test_r4_the_07_rule_still_applies_to_the_claude_answer(monkeypatch):
    monkeypatch.setattr(classify, "_judge", lambda e, c: None)
    monkeypatch.setattr(classify, "_claude", lambda e, c: _probs(FC.DOCS_BUG, 0.6))
    asked = []
    cls, src = recovery.resolve_class("odd error", "cmd", asker=lambda q: asked.append(q) or "p")
    assert (cls, src) == (FC.PRODUCT_BUG, "human") and len(asked) == 1


@pytest.mark.parametrize("reply", [{"choices": [{"message": {"content": "not json"}}]}, {"oops": 1},
                                   {"choices": [{"message": {"content": '{"results": []}'}}]}, None])
def test_r4_judge_http_garbage_or_error_returns_none(monkeypatch, reply):
    monkeypatch.delenv("ONESTRUN_JUDGE", raising=False)
    monkeypatch.setenv("ONESTRUN_JUDGE_BASE_URL", "http://judge.test/v1")

    def post(*a, **k):
        if reply is None:
            raise httpx.ConnectError("down")
        return httpx.Response(200, json=reply, request=httpx.Request("POST", "https://x"))

    monkeypatch.setattr(httpx, "post", post)
    assert classify._judge("err", "cmd") is None


def test_r4_every_model_failure_ends_in_the_heuristic(monkeypatch):
    monkeypatch.setattr(classify, "_judge", lambda e, c: None)
    monkeypatch.setattr(classify, "_claude", lambda e, c: None)
    assert classify.classify("ModuleNotFoundError: No module named x", "python x.py").source == "heuristic"


# --- R5, R6 --------------------------------------------------------------------

def test_r5_top_probability_069_asks_the_user_once(monkeypatch):
    judge(monkeypatch, FC.DOCS_BUG, 0.69)
    asked = []
    recovery.resolve_class("weird 1", "c", asker=lambda q: asked.append(q) or "d")
    assert len(asked) == 1


def test_r6_top_probability_070_does_not_ask(monkeypatch):
    judge(monkeypatch, FC.DOCS_BUG, 0.70)
    cls, src = recovery.resolve_class("weird 2", "c", asker=lambda q: pytest.fail("asked"))
    assert (cls, src) == (FC.DOCS_BUG, "judge")


def test_r6_exactly_070_from_the_wire_does_not_ask(monkeypatch):
    """Normalizing 0.7, 0.1, 0.1, 0.1 must not tip the answer under 0.7 through float error."""
    monkeypatch.setattr(classify, "_claude", lambda e, c: None)
    monkeypatch.delenv("ONESTRUN_JUDGE", raising=False)
    monkeypatch.setenv("ONESTRUN_JUDGE_BASE_URL", "http://judge.test/v1")
    answer = {"results": [{"id": 0, "failure_class": {"docs_bug": 0.7, "environment": 0.1,
                                                      "product_bug": 0.1, "needs_secret": 0.1}}]}
    body = {"choices": [{"message": {"content": json.dumps(answer)}}], "usage": {"prompt_tokens": 50}}
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(200, json=body, request=httpx.Request("POST", "https://x")))
    cls, _ = recovery.resolve_class("weird 3", "c", asker=lambda q: pytest.fail("asked"))
    assert cls == FC.DOCS_BUG


# --- R7 ------------------------------------------------------------------------

def test_r7_same_signature_again_uses_the_precedent(monkeypatch):
    judge(monkeypatch, FC.DOCS_BUG, 0.3)
    asked = []
    first = recovery.resolve_class("E: Unable to locate package foo at /tmp/a1 line 12", "c", asker=lambda q: asked.append(q) or "e")
    again = recovery.resolve_class("E: Unable to locate package foo at /var/b2 line 99", "c", asker=lambda q: asked.append(q) or "e")
    assert first == (FC.ENVIRONMENT, "human") and again == (FC.ENVIRONMENT, "precedent")
    assert len(asked) == 1


# --- R8 ------------------------------------------------------------------------

@pytest.mark.parametrize("content", ["{not json at all", "", "[1, 2]"])
def test_r8_corrupt_or_empty_precedents_are_moved_aside_and_rebuilt(tmp_precedents, monkeypatch, content):
    tmp_precedents.write_text(content, encoding="utf-8")
    judge(monkeypatch, FC.ENVIRONMENT, 0.95)
    cls, _ = recovery.resolve_class("curl: not found", "curl x")     # the run continues
    assert cls == FC.ENVIRONMENT
    aside = list(tmp_precedents.parent.glob("precedents.json.corrupt-*"))
    assert len(aside) == 1 and aside[0].read_text(encoding="utf-8") == content
    precedents.store("sig", FC.DOCS_BUG)                             # a new, valid file
    assert json.loads(tmp_precedents.read_text(encoding="utf-8"))["sig"]["class"] == "docs_bug"
    assert precedents.lookup("sig") == FC.DOCS_BUG


# --- R9 ------------------------------------------------------------------------

def test_r9_timeout_is_60_seconds():
    assert recovery.ASK_TIMEOUT_S == 60


def test_r9_terminal_asker_raises_after_the_timeout(monkeypatch):
    import sys
    import time

    class Tty:
        def isatty(self):
            return True

    monkeypatch.setattr(sys, "stdin", Tty())
    monkeypatch.setattr(builtins, "input", lambda prompt="": time.sleep(5))
    monkeypatch.setattr(recovery, "ASK_TIMEOUT_S", 0.2)
    with pytest.raises(recovery.AskTimeout):
        recovery._terminal_asker("question?")


def test_r9_no_answer_marks_the_step_needs_human_and_the_run_ends_with_a_report(tmp_runs_dir, monkeypatch):
    judge(monkeypatch, FC.DOCS_BUG, 0.3)

    def silent(question):
        raise recovery.AskTimeout("no answer")

    fake = FakeContainer({"bad": (1, "", "weird failure")})
    state = executor.run(make_runbook("bad", "after"), run_id="r9", container_factory=factory_for(fake),
                         recover=lambda s, r, st, d: recovery.recover(s, r, st, d, asker=silent))
    assert state.step_status[1] == StepStatus.NEEDS_HUMAN and state.status == RunStatus.FAILED
    assert "needs_human" in state.stop_reason and state.finished_at
    assert "needs_human" in (tmp_runs_dir / "r9" / "report.md").read_text(encoding="utf-8")


# --- R10 -----------------------------------------------------------------------

def test_r10_product_bug_gets_no_patch_and_no_pr_text(tmp_runs_dir, monkeypatch):
    judge(monkeypatch, FC.PRODUCT_BUG, 0.95)
    rb = make_runbook("tool run")
    fake = FakeContainer({"tool run": (1, "", "Segmentation fault (core dumped)")})
    state = executor.run(rb, run_id="r10", container_factory=factory_for(fake), recover=recovery.recover,
                         verify=lambda r, s: pytest.fail("verified a product bug"))
    assert state.patches == [] and state.status == RunStatus.FAILED
    report = (tmp_runs_dir / "r10" / "report.md").read_text(encoding="utf-8")
    assert "product bug" in report.lower()
    assert patch.write_outputs(tmp_runs_dir / "r10", state, rb) == []
    assert not (tmp_runs_dir / "r10" / "pr_body.md").exists() and not (tmp_runs_dir / "r10" / "patch.diff").exists()


# --- R11 -----------------------------------------------------------------------

def test_r11_needs_secret_without_a_test_key_stops_and_invents_nothing(monkeypatch):
    judge(monkeypatch, FC.NEEDS_SECRET, 0.95)
    step, res = _fail("python app.py", "openai.AuthenticationError: OPENAI_API_KEY is not set")
    out = recovery.recover(step, res, _state(), "Set OPENAI_API_KEY first.")
    assert not isinstance(out, Patch)
    assert out.failure_class == FC.NEEDS_SECRET and "allowlist" in out.reason


def test_r11_a_listed_key_is_used_by_name_and_never_shown(monkeypatch, tmp_path):
    allow = tmp_path / "allow"
    allow.write_text("OPENAI_API_KEY=sk-test-VALUE-1234567\n", encoding="utf-8")
    monkeypatch.setattr(config, "SECRETS_ALLOWLIST", allow)
    judge(monkeypatch, FC.NEEDS_SECRET, 0.95)
    step, res = _fail("python app.py", "OPENAI_API_KEY is not set")
    out = recovery.recover(step, res, _state(), "")
    # The key was already in the container, so 1stRun stops instead of retrying the same command.
    assert isinstance(out, GaveUp) and "OPENAI_API_KEY" in out.reason
    assert "sk-test-VALUE-1234567" not in out.model_dump_json()


# --- R12 -----------------------------------------------------------------------

def test_r12_empty_fix_search_gives_up_with_the_search_terms_logged(monkeypatch):
    rec = install_recorder(monkeypatch)
    judge(monkeypatch, FC.DOCS_BUG, 0.95)
    monkeypatch.setattr(llm, "ask_json", lambda *a, **k: ({"new_command": "", "reason": "nothing"}, {}))
    step, res = _fail()
    out = recovery.recover(step, res, _state(), "docs")
    assert not isinstance(out, Patch) and "searched:" in out.reason
    assert "pip" in out.reason and "No matching distribution" in out.reason
    assert "fix search found nothing" in rec.log_text() and "No matching distribution" in rec.log_text()


# --- K7 ------------------------------------------------------------------------

NET_ERR = "WARNING: Retrying after ConnectionError: Temporary failure in name resolution"


def test_k7_network_drop_is_environment_and_retried_once(monkeypatch):
    judge(monkeypatch, FC.DOCS_BUG, 0.95)                       # even a wrong model answer does not matter
    state = _state()
    step, res = _fail("pip install requests", NET_ERR)
    first = recovery.recover(step, res, state, "")
    assert isinstance(first, Patch) and first.failure_class == FC.ENVIRONMENT
    assert first.new_command == step.command and first.source == "retry"
    assert state.classifications[1].top == FC.ENVIRONMENT
    state.patches.append(first)
    second = recovery.recover(step, res, state, "")
    assert not isinstance(second, Patch) and second.failure_class == FC.ENVIRONMENT


def test_k7_run_passes_when_the_retry_succeeds(tmp_runs_dir):
    calls = []

    def flaky(command):
        calls.append(command)
        return (1, "", NET_ERR) if len(calls) == 1 else (0, "ok", "")

    state = executor.run(make_runbook("pip install requests"), run_id="k7", recover=recovery.recover,
                         container_factory=factory_for(FakeContainer({"pip install requests": flaky})))
    assert state.status == RunStatus.PASSED and state.attempts[1] == 2


# --- K8 ------------------------------------------------------------------------

def test_k8_secret_shapes_are_redacted():
    text = f"key {SECRET} and GITHUB_TOKEN=ghp_abcdefghijklmnopqrstuv and Authorization: Bearer abcdefghijklmnopqrstuvwx"
    out = redact(text)
    assert SECRET not in out and "ghp_abc" not in out and "abcdefghijklmnopqr" not in out
    assert out.count(MARK) == 3
    assert redact("OPENAI_API_KEY is not set") == "OPENAI_API_KEY is not set"   # names stay, so classification works


def test_k8_exact_allowlist_values_are_redacted(monkeypatch, tmp_path):
    allow = tmp_path / "allow"
    allow.write_text("DEMO_KEY=plain-value-no-shape\n", encoding="utf-8")
    monkeypatch.setattr(config, "SECRETS_ALLOWLIST", allow)
    assert redact("login with plain-value-no-shape now") == f"login with {MARK} now"


def test_k8_secret_never_reaches_state_report_span_or_logs(tmp_runs_dir, monkeypatch):
    rec = install_recorder(monkeypatch)
    judge(monkeypatch, FC.PRODUCT_BUG, 0.95)
    fake = FakeContainer({"run": (1, f"token={SECRET}", f"fatal: bad credential {SECRET}")})
    state = executor.run(make_runbook("run"), run_id="k8", recover=recovery.recover, container_factory=factory_for(fake))
    run_dir = tmp_runs_dir / "k8"
    for name in ("state.json", "report.md"):
        assert SECRET not in (run_dir / name).read_text(encoding="utf-8"), name
    assert MARK in (run_dir / "state.json").read_text(encoding="utf-8")
    assert SECRET not in rec.log_text() and SECRET not in str(rec.spans)
    assert SECRET not in state.model_dump_json()


def test_k8_container_exec_redacts_at_the_source(monkeypatch):
    class Proc:
        returncode = 1

        def __init__(self, *a, **k):
            pass

        def communicate(self, data, timeout=None):
            return SECRET.encode(), f"err {SECRET}".encode()

    monkeypatch.setattr(sandbox.subprocess, "Popen", Proc)
    res = sandbox.Container("python:3.11-slim", name="1stRun-t7-fake").exec("x")
    assert SECRET not in res.stdout + res.stderr and MARK in res.stdout
