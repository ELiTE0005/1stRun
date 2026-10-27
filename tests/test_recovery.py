"""T4: ask-once, budget, recover."""

import pytest

from onestrun import budget, classify, llm, precedents, recovery
from onestrun.budget import BudgetExceeded
from onestrun.models import Budget, FailureClass as FC, GaveUp, Patch, RunState, Step, StepResult

PIP_ERR = "ERROR: No matching distribution found for chromadb==0.3"


def _probs(top, p=0.95):
    rest = (1 - p) / 3
    return {c: (p if c == top else rest) for c in FC}


def _state():
    return RunState(run_id="r1", source_url="http://x")


def _step(cmd="pip install chromadb==0.3"):
    return Step(id=2, intent="install", command=cmd)


def _result(cmd, err, code=1):
    return StepResult(step_id=2, command=cmd, exit_code=code, stderr=err)


@pytest.fixture(autouse=True)
def _no_net(monkeypatch):
    monkeypatch.setattr(recovery, "_pypi_hint", lambda e: "")


# --- ask once ---------------------------------------------------------------

def test_ask_once_then_reuse(tmp_precedents, monkeypatch):
    monkeypatch.setattr(classify, "_claude", lambda e, c: None)  # the judge answers, so Claude must not run
    monkeypatch.setattr(classify, "_judge", lambda e, c: _probs(FC.DOCS_BUG, 0.4))
    questions = []

    def asker(q):
        questions.append(q)
        return "e"

    first = recovery.resolve_class("weird failure 12", "cmd", asker=asker, step_id=3)
    assert first == (FC.ENVIRONMENT, "human")
    assert len(questions) == 1 and questions[0].startswith("Step 3 failed: weird failure 12.")
    assert "[d/e/p/s]" in questions[0]
    second = recovery.resolve_class("weird failure 99", "cmd", asker=asker)
    assert second == (FC.ENVIRONMENT, "precedent")
    assert len(questions) == 1


def test_confident_answer_asks_nothing(tmp_precedents, monkeypatch):
    monkeypatch.setattr(classify, "_claude", lambda e, c: None)  # the judge answers, so Claude must not run
    monkeypatch.setattr(classify, "_judge", lambda e, c: _probs(FC.DOCS_BUG, 0.8))
    cls, src = recovery.resolve_class("err", "c", asker=lambda q: pytest.fail("asked"))
    assert (cls, src) == (FC.DOCS_BUG, "judge")
    assert precedents.lookup(classify.signature("err")) is None  # 0.8 is below the store bar


def test_very_confident_answer_is_stored(tmp_precedents, monkeypatch):
    monkeypatch.setattr(classify, "_claude", lambda e, c: None)  # the judge answers, so Claude must not run
    monkeypatch.setattr(classify, "_judge", lambda e, c: _probs(FC.DOCS_BUG, 0.95))
    recovery.resolve_class("err", "c")
    assert precedents.lookup(classify.signature("err")) == FC.DOCS_BUG


def test_no_tty_no_asker_uses_top_class(tmp_precedents, monkeypatch):
    monkeypatch.setattr(classify, "_claude", lambda e, c: None)  # the judge answers, so Claude must not run
    monkeypatch.setattr(classify, "_judge", lambda e, c: _probs(FC.PRODUCT_BUG, 0.4))
    monkeypatch.setattr("sys.stdin", None)
    assert recovery.resolve_class("err", "c")[0] == FC.PRODUCT_BUG
    assert precedents.lookup(classify.signature("err")) is None


# --- budget -----------------------------------------------------------------

def test_budget_passes_then_trips_on_tool_calls():
    s, b = _state(), Budget()
    s.usage.tool_calls = 24
    budget.check(s, b, 1)
    s.usage.tool_calls = 25
    with pytest.raises(BudgetExceeded, match="tool call"):
        budget.check(s, b, 1)


def test_budget_trips_on_cost_and_attempts():
    s, b = _state(), Budget()
    s.usage.cost_usd = 0.50
    with pytest.raises(BudgetExceeded, match="cost"):
        budget.check(s, b)
    s.usage.cost_usd = 0.1
    s.attempts[4] = 3
    with pytest.raises(BudgetExceeded, match="attempt"):
        budget.check(s, b, 4)
    budget.check(s, b, 5)


# --- recover ----------------------------------------------------------------

def test_recover_docs_bug_returns_patch(tmp_precedents, monkeypatch):
    monkeypatch.setattr(classify, "_claude", lambda e, c: None)  # the judge answers, so Claude must not run
    monkeypatch.setattr(classify, "_judge", lambda e, c: _probs(FC.DOCS_BUG))
    seen = {}

    def fake(prompt, system="", tools=(), max_turns=1):
        seen.update(prompt=prompt, tools=tools, max_turns=max_turns)
        return ({"new_command": "pip install chromadb==0.5.0", "reason": "0.3 was yanked",
                 "source": "https://pypi.org/project/chromadb/"},
                {"input_tokens": 100, "output_tokens": 20, "tool_calls": 2, "cost_usd": 0.01})

    monkeypatch.setattr(llm, "ask_json", fake)
    s = _state()
    out = recovery.recover(_step(), _result("pip install chromadb==0.3", PIP_ERR), s, docs_markdown="# Docs")
    assert isinstance(out, Patch) and out.new_command == "pip install chromadb==0.5.0"
    assert out.failure_class == FC.DOCS_BUG and out.source.startswith("https://")
    assert list(seen["tools"]) == ["WebSearch", "WebFetch"]
    assert "chromadb==0.3" in seen["prompt"]
    assert s.usage.tool_calls == 2 and s.usage.cost_usd == pytest.approx(0.01)
    assert s.classifications[2].top == FC.DOCS_BUG


def test_recover_gives_up_when_model_repeats_earlier_patch(tmp_precedents, monkeypatch):
    monkeypatch.setattr(classify, "_claude", lambda e, c: None)  # the judge answers, so Claude must not run
    monkeypatch.setattr(classify, "_judge", lambda e, c: _probs(FC.DOCS_BUG))
    monkeypatch.setattr(llm, "ask_json", lambda *a, **k: ({"new_command": "pip install chromadb==0.5.0"}, {}))
    s = _state()
    s.patches.append(Patch(step_id=2, old_command="x", new_command="pip install chromadb==0.5.0", reason="r"))
    out = recovery.recover(_step(), _result("pip install chromadb==0.5.0", PIP_ERR), s)
    assert isinstance(out, GaveUp)


def test_recover_environment_curl_patch_needs_no_model(tmp_precedents, monkeypatch):
    monkeypatch.setattr(classify, "_claude", lambda e, c: None)  # the judge answers, so Claude must not run
    monkeypatch.setattr(classify, "_judge", lambda e, c: _probs(FC.ENVIRONMENT))
    monkeypatch.setattr(llm, "ask_json", lambda *a, **k: pytest.fail("no model needed"))
    out = recovery.recover(_step("curl -sSL x | sh"), _result("curl -sSL x | sh", "sh: 1: curl: not found", 127), _state())
    assert isinstance(out, Patch) and out.failure_class == FC.ENVIRONMENT
    assert out.new_command == "apt-get update -qq && apt-get install -y -qq curl && curl -sSL x | sh"


def test_recover_product_bug_gives_up(tmp_precedents, monkeypatch):
    monkeypatch.setattr(classify, "_claude", lambda e, c: None)  # the judge answers, so Claude must not run
    monkeypatch.setattr(classify, "_judge", lambda e, c: _probs(FC.PRODUCT_BUG))
    out = recovery.recover(_step("tool run"), _result("tool run", "panic: runtime error"), _state())
    assert isinstance(out, GaveUp) and out.reason.startswith("product bug:")
    assert out.failure_class == FC.PRODUCT_BUG


def test_recover_needs_secret_uses_allowlist(tmp_path, tmp_precedents, monkeypatch):
    allow = tmp_path / "secrets.allowlist"
    allow.write_text("DEMO_API_KEY=test-value\n")
    monkeypatch.setattr(recovery.config, "SECRETS_ALLOWLIST", allow)
    monkeypatch.setattr(classify, "_claude", lambda e, c: None)  # the judge answers, so Claude must not run
    monkeypatch.setattr(classify, "_judge", lambda e, c: _probs(FC.NEEDS_SECRET))
    out = recovery.recover(_step("tool run"), _result("tool run", "Error: DEMO_API_KEY is not set"), _state())
    # The key was already in the container, so 1stRun stops instead of retrying the same command.
    assert isinstance(out, GaveUp) and "DEMO_API_KEY" in out.reason
    assert "test-value" not in out.model_dump_json()  # the secret value never leaks
    out2 = recovery.recover(_step("tool run"), _result("tool run", "Error: OTHER_API_KEY is not set"), _state())
    assert isinstance(out2, GaveUp)


def test_recover_stops_when_budget_is_spent(tmp_precedents, monkeypatch):
    monkeypatch.setattr(classify, "_claude", lambda e, c: None)  # the judge answers, so Claude must not run
    monkeypatch.setattr(classify, "_judge", lambda e, c: _probs(FC.DOCS_BUG))
    monkeypatch.setattr(llm, "ask_json", lambda *a, **k: pytest.fail("budget must block the call"))
    s = _state()
    s.usage.tool_calls = 25
    out = recovery.recover(_step(), _result("pip install chromadb==0.3", PIP_ERR), s)
    assert isinstance(out, GaveUp) and "tool call budget" in out.reason


@pytest.mark.live
def test_live_recover_returns_real_patch(tmp_precedents):
    s = _state()
    out = recovery.recover(_step(), _result("pip install chromadb==0.3", PIP_ERR), s,
                           docs_markdown="Install with: pip install chromadb==0.3")
    print("recover returned:", out, s.usage, s.classifications.get(2))
    assert isinstance(out, Patch) and out.new_command != "pip install chromadb==0.3"
    assert out.failure_class == FC.DOCS_BUG


def test_terminal_asker_returns_none_on_eof(monkeypatch):
    import builtins
    import io

    from onestrun import recovery

    class TtyIn(io.StringIO):
        def isatty(self):
            return True

    def no_reader(_prompt=""):
        raise EOFError

    monkeypatch.setattr(recovery.sys, "stdin", TtyIn())
    monkeypatch.setattr(builtins, "input", no_reader)
    assert recovery._terminal_asker("Docs bug?") is None


def test_short_reason_ends_on_a_sentence():
    from onestrun.recovery import _short_reason

    text = "First sentence is here. " * 30
    out = _short_reason(text)
    assert len(out) <= 400 and out.endswith(".")
    assert _short_reason("Short reason.") == "Short reason."


def test_error_text_drops_pip_noise_and_keeps_the_real_error():
    from onestrun.models import StepResult
    from onestrun.recovery import _error_text

    noise = "\n".join(f"Collecting pkg{i}" for i in range(400)) + "\nSuccessfully installed openai-0.28.1"
    r = StepResult(step_id=5, command="python quickstart.py", exit_code=1, stdout=noise,
                   stderr="Traceback (most recent call last):\nopenai.error.AuthenticationError: No API key provided.")
    text = _error_text(r)
    assert "AuthenticationError" in text and "Collecting" not in text


def test_apt_only_fix_counts_as_environment():
    from onestrun.recovery import _APT

    assert _APT.search("apt-get update -qq && apt-get install -y -qq curl && entire version")
    assert not _APT.search("pip install chromadb")
