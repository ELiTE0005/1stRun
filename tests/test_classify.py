"""T4: classification fallback order, signatures, precedents."""

import json

import pytest

from firstrun import classify, llm, precedents
from firstrun.models import FailureClass as FC

PIP_ERR = "ERROR: Could not find a version that satisfies the requirement chromadb==0.3\nERROR: No matching distribution found for chromadb==0.3"


def _probs(top, p=0.9):
    rest = (1 - p) / 3
    return {c: (p if c == top else rest) for c in FC}


def test_signature_is_stable_across_paths_numbers_and_hashes():
    a = classify.signature("Traceback\n  File '/tmp/abc123/x.py', line 12\nModuleNotFoundError: No module named 'foo'")
    b = classify.signature("Traceback\n  File '/home/u/other/x.py', line 99\nModuleNotFoundError: No module named 'foo'")
    assert a == b
    assert classify.signature("error 0xdeadbeef at 12") == classify.signature("error 0xcafebabe at 7")
    assert classify.signature("curl: not found") != classify.signature(PIP_ERR)


def test_signature_has_readable_prefix_and_short_hash():
    sig = classify.signature(PIP_ERR)
    assert sig.startswith("error-no-matching")
    assert len(sig.rsplit("-", 1)[1]) == 12


def test_jev_wins_when_it_answers(monkeypatch):
    monkeypatch.setattr(classify, "_jev", lambda e, c: _probs(FC.DOCS_BUG))
    monkeypatch.setattr(llm, "ask_json", lambda *a, **k: pytest.fail("claude must not run"))
    cls = classify.classify(PIP_ERR, "pip install chromadb==0.3")
    assert cls.source == "jev" and cls.top == FC.DOCS_BUG


def test_claude_is_the_fallback(monkeypatch):
    monkeypatch.setattr(classify, "_jev", lambda e, c: None)
    reply = {"docs_bug": 0.1, "environment": 0.7, "product_bug": 0.1, "needs_secret": 0.1}
    monkeypatch.setattr(llm, "ask_json", lambda *a, **k: (reply, {"cost_usd": 0.001}))
    cls = classify.classify("boom", "x")
    assert cls.source == "claude" and cls.top == FC.ENVIRONMENT


def test_heuristic_is_the_last_fallback(monkeypatch):
    monkeypatch.setattr(classify, "_jev", lambda e, c: None)

    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(llm, "ask_json", boom)
    cls = classify.classify(PIP_ERR, "pip install chromadb==0.3")
    assert cls.source == "heuristic" and cls.top == FC.DOCS_BUG
    assert classify.classify("sh: 1: curl: not found", "curl x").top == FC.ENVIRONMENT
    assert classify.classify("Error: OPENAI_API_KEY is not set", "x").top == FC.NEEDS_SECRET
    assert classify.classify("Segmentation fault (core dumped)", "x").top == FC.PRODUCT_BUG
    assert classify.classify("something odd", "x").confidence < 0.7


def test_precedent_store_and_lookup(tmp_precedents):
    assert precedents.lookup("sig-1") is None
    precedents.store("sig-1", FC.ENVIRONMENT, example="x" * 500)
    assert precedents.lookup("sig-1") == FC.ENVIRONMENT
    entry = json.loads(tmp_precedents.read_text())["sig-1"]
    assert entry["class"] == "environment" and len(entry["example"]) == 200 and entry["stored_at"]


@pytest.mark.live
def test_live_jev_classifies_pip_version_as_docs_bug():
    probs = classify._jev(PIP_ERR, "pip install chromadb==0.3")
    print("jev returned:", probs)
    assert probs is not None
    assert max(probs, key=probs.get) == FC.DOCS_BUG
