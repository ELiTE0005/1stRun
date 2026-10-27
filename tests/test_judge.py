"""The judge model client. No model is called: httpx is replaced."""

from __future__ import annotations

import json

import httpx
import pytest

from onestrun import judge

CLASSES = {"a": "first", "b": "second"}


def _reply(results, tokens=40):
    return {"choices": [{"message": {"content": json.dumps({"results": results})}}], "usage": {"prompt_tokens": tokens}}


@pytest.fixture
def on(monkeypatch):
    """A judge that is switched on, with a recorder for every request."""
    monkeypatch.delenv("ONESTRUN_JUDGE", raising=False)
    monkeypatch.setenv("ONESTRUN_JUDGE_BASE_URL", "http://judge.test/v1")
    monkeypatch.delenv("ONESTRUN_JUDGE_API_KEY", raising=False)
    judge.reset()
    judge.reset_usage()
    calls = []

    def install(handler):
        def post(url, json=None, headers=None, timeout=None):
            calls.append({"url": url, "body": json, "headers": headers})
            status, body = handler(json)
            return httpx.Response(status, json=body, request=httpx.Request("POST", url))
        monkeypatch.setattr(httpx, "post", post)
        return calls
    return install


def test_choice_and_score_answers_are_normalized_and_clamped(on):
    calls = on(lambda b: (200, _reply([{"id": 0, "kind": {"a": 3, "b": 1}, "p": 1.7}])))
    out = judge.ask([{"t": "x"}], {"kind": judge.Choice("which?", CLASSES), "p": judge.Score("true?")})
    assert out == [{"kind": {"a": 0.75, "b": 0.25}, "p": 1.0}]
    assert calls[0]["url"] == "http://judge.test/v1/chat/completions"
    assert calls[0]["body"]["temperature"] == 0 and calls[0]["body"]["model"] == judge.DEFAULT_MODEL
    assert judge.USAGE == {"calls": 1, "input_tokens": 40, "cost_usd": 0.0}


def test_a_long_list_is_split_so_each_call_fits_a_small_context(on, monkeypatch):
    monkeypatch.setenv("ONESTRUN_JUDGE_CHUNK_CHARS", "300")
    seen = []

    def handler(body):
        ids = [int(x) for x in __import__("re").findall(r'"id": (\d+)', body["messages"][1]["content"].split("Items:")[1].split("Reply with")[0])]
        seen.append(ids)
        return 200, _reply([{"id": i, "p": 0.5} for i in ids])

    on(handler)
    out = judge.ask([{"text": "x" * 100} for _ in range(8)], {"p": judge.Score("q")})
    assert all(a == {"p": 0.5} for a in out) and len(seen) > 1
    assert sorted(i for ids in seen for i in ids) == list(range(8))


def test_an_item_the_model_skipped_or_garbled_is_none_and_the_rest_survive(on):
    on(lambda b: (200, _reply([{"id": 0, "p": 0.2}, {"id": 1, "p": "high"}, {"id": 5, "p": 0.9}])))
    assert judge.ask([{"t": 1}, {"t": 2}, {"t": 3}], {"p": judge.Score("q")}) == [{"p": 0.2}, None, None]


@pytest.mark.parametrize("content", ["not json at all", "```json\n{\"results\": [{\"id\": 0, \"p\": 0.3}]}\n```",
                                     "Sure! {\"results\": [{\"id\": 0, \"p\": 0.3}]} Hope that helps."])
def test_fenced_or_chatty_replies_are_still_read(on, content):
    on(lambda b: (200, {"choices": [{"message": {"content": content}}]}))
    out = judge.ask([{"t": 1}], {"p": judge.Score("q")})
    assert out == ([None] if content == "not json at all" else [{"p": 0.3}])


def test_an_endpoint_without_json_mode_is_asked_again_without_it(on):
    calls = on(lambda b: (400, {"error": "response_format"}) if "response_format" in b
               else (200, _reply([{"id": 0, "p": 0.4}])))
    assert judge.ask([{"t": 1}], {"p": judge.Score("q")}) == [{"p": 0.4}]
    assert len(calls) == 2 and "response_format" not in calls[1]["body"]


def test_a_failing_endpoint_never_raises(on, monkeypatch):
    on(lambda b: (500, {"error": "down"}))
    assert judge.ask([{"t": 1}, {"t": 2}], {"p": judge.Score("q")}) == [None, None]

    def boom(*a, **k):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "post", boom)
    assert judge.ask([{"t": 1}], {"p": judge.Score("q")}) == [None]


def test_a_cloud_key_goes_in_the_bearer_header(on, monkeypatch):
    monkeypatch.setenv("ONESTRUN_JUDGE_API_KEY", "test-key-value")
    monkeypatch.setenv("ONESTRUN_JUDGE_MODEL", "some-model")
    calls = on(lambda b: (200, _reply([{"id": 0, "p": 0.1}])))
    judge.ask([{"t": 1}], {"p": judge.Score("q")})
    assert calls[0]["headers"] == {"Authorization": "Bearer test-key-value"}
    assert calls[0]["body"]["model"] == "some-model"


def test_off_switch_beats_everything(monkeypatch):
    monkeypatch.setenv("ONESTRUN_JUDGE", "off")
    monkeypatch.setenv("ONESTRUN_JUDGE_BASE_URL", "http://judge.test/v1")
    assert not judge.available()
    assert judge.ask([{"t": 1}], {"p": judge.Score("q")}) == [None]


def _tags(monkeypatch, names):
    monkeypatch.setenv("ONESTRUN_JUDGE", "ollama")
    monkeypatch.delenv("ONESTRUN_JUDGE_BASE_URL", raising=False)
    monkeypatch.setattr(judge.config, "load_env", lambda *a, **k: None)
    judge.reset()
    monkeypatch.setattr(httpx, "get", lambda url, timeout=None: httpx.Response(
        200, json={"models": [{"name": n} for n in names]}, request=httpx.Request("GET", url)))


def test_a_local_ollama_with_the_model_is_found(monkeypatch):
    _tags(monkeypatch, ["qwen2.5:7b", "llama3:8b"])
    assert judge.available()


def test_ollama_without_the_model_says_how_to_pull_it(monkeypatch, capsys):
    _tags(monkeypatch, ["llama3:8b"])
    assert not judge.available()
    assert "ollama pull qwen2.5:7b" in capsys.readouterr().err


def test_no_ollama_means_no_judge_and_no_noise(monkeypatch, capsys):
    monkeypatch.setenv("ONESTRUN_JUDGE", "ollama")
    monkeypatch.delenv("ONESTRUN_JUDGE_BASE_URL", raising=False)
    monkeypatch.setattr(judge.config, "load_env", lambda *a, **k: None)
    judge.reset()

    def refuse(url, timeout=None):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "get", refuse)
    assert not judge.available()
    assert capsys.readouterr().err == ""


# --- the Claude backend and how a backend is picked ---------------------------------

@pytest.fixture
def env(monkeypatch):
    """A clean judge environment: no mode, no endpoint, no token, no Ollama."""
    for k in ("ONESTRUN_JUDGE", "ONESTRUN_JUDGE_BASE_URL", "CLAUDE_CODE_OAUTH_TOKEN", "ONESTRUN_JUDGE_CLAUDE_MODEL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(judge.config, "load_env", lambda *a, **k: None)
    judge.reset()
    judge.reset_usage()
    monkeypatch.setattr(httpx, "get", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("refused")))
    return monkeypatch


def test_claude_is_the_default_when_a_token_is_set(env):
    assert judge.backend() is None
    env.setenv("CLAUDE_CODE_OAUTH_TOKEN", "test-value")
    assert judge.backend() == "claude"
    assert judge.backend("local") is None  # the local backend is still unreachable


def test_an_explicit_choice_beats_the_default(env):
    env.setenv("CLAUDE_CODE_OAUTH_TOKEN", "test-value")
    env.setenv("ONESTRUN_JUDGE_BASE_URL", "http://judge.test/v1")
    assert judge.backend() == "local"            # a configured endpoint wins over the auto order
    env.setenv("ONESTRUN_JUDGE", "claude")
    assert judge.backend() == "claude"           # the mode wins over the endpoint
    env.setenv("ONESTRUN_JUDGE", "off")
    assert judge.backend() is None and judge.backend("local") is None


def test_claude_answers_in_big_chunks_and_the_cost_is_counted(env, monkeypatch):
    env.setenv("CLAUDE_CODE_OAUTH_TOKEN", "test-value")
    env.setenv("ONESTRUN_JUDGE_CLAUDE_MODEL", "some-claude")
    seen = []

    def ask_json(prompt, system="", tools=(), max_turns=1, model=None):
        import re
        ids = [int(x) for x in re.findall(r'"id": (\d+)', prompt.split("Items:")[1].split("Reply with")[0])]
        seen.append((ids, model))
        return {"results": [{"id": i, "p": 0.25} for i in ids]}, {"input_tokens": 700, "cost_usd": 0.002}

    from onestrun import llm
    monkeypatch.setattr(llm, "ask_json", ask_json)
    out = judge.ask([{"text": "x" * 100} for _ in range(40)], {"p": judge.Score("q")})
    assert all(a == {"p": 0.25} for a in out)
    assert len(seen) == 1 and seen[0][1] == "some-claude"        # 40 small items fit one call
    assert judge.USAGE["calls"] == 1 and judge.USAGE["cost_usd"] == pytest.approx(0.002)
    assert judge.last_backend() == "claude"


def test_a_blocked_model_call_is_never_swallowed(env, monkeypatch):
    env.setenv("CLAUDE_CODE_OAUTH_TOKEN", "test-value")
    from onestrun import llm
    monkeypatch.setattr(llm, "ask_json", lambda *a, **k: (_ for _ in ()).throw(judge.config.ModelCallBlocked("no")))
    with pytest.raises(judge.config.ModelCallBlocked):
        judge.ask([{"t": 1}], {"p": judge.Score("q")})


def test_a_claude_failure_leaves_the_items_unanswered(env, monkeypatch):
    env.setenv("CLAUDE_CODE_OAUTH_TOKEN", "test-value")
    from onestrun import llm
    monkeypatch.setattr(llm, "ask_json", lambda *a, **k: (_ for _ in ()).throw(llm.ModelAuthError("expired")))
    assert judge.ask([{"t": 1}, {"t": 2}], {"p": judge.Score("q")}) == [None, None]


def test_prefer_local_never_calls_claude(env, monkeypatch):
    env.setenv("CLAUDE_CODE_OAUTH_TOKEN", "test-value")
    from onestrun import llm
    monkeypatch.setattr(llm, "ask_json", lambda *a, **k: pytest.fail("Claude must not run"))
    assert judge.ask([{"t": 1}], {"p": judge.Score("q")}, prefer="local") == [None]
