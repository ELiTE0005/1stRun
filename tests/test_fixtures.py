from pathlib import Path

import pytest

from onestrun.models import Runbook

FIX = Path(__file__).parent / "fixtures"
DOCS = sorted((FIX / "docs").glob("*.md"))
RUNBOOKS = sorted((FIX / "runbooks").glob("*.json"))


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_doc_loads(doc):
    text = doc.read_text(encoding="utf-8")
    assert len(text) > 100


@pytest.mark.parametrize("rb", RUNBOOKS, ids=lambda p: p.name)
def test_runbook_validates(rb):
    book = Runbook.model_validate_json(rb.read_text(encoding="utf-8"))
    assert book.steps and book.source_url.startswith("file://tests/fixtures/docs/")


def test_fixture_labels():
    for doc in DOCS:
        first = doc.read_text(encoding="utf-8").splitlines()[0]
        if doc.name.endswith("_FIXTURE.md"):
            assert "FIXTURE" in first, doc.name
        else:
            assert "Source: https://" in first and "2026-10-10" in first, doc.name
    assert len(DOCS) >= 6


def test_fixtures_via_conftest(load_doc, load_runbook, fake_llm, tmp_runs_dir, tmp_precedents):
    assert "chromadb==0.3" in load_doc("broken_quickstart_FIXTURE")
    assert len(load_runbook("broken_quickstart").steps) == 4
    assert load_runbook("two_step_ok").steps[1].expected.output_contains == "2"
    llm = fake_llm(["a", "b"])
    assert (llm("x"), llm("y")) == ("a", "b")
    assert tmp_runs_dir.exists()


@pytest.mark.live
def test_live_skipped_by_default():
    raise AssertionError("must be skipped unless ONESTRUN_LIVE=1")
