"""T6 tests. Offline only. Render the sample runs and check the page."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from onestrun.report_html import write_html

FIX = Path(__file__).parent / "fixtures_report"


def _render(tmp_path: Path, extras=None, runs: Path = FIX) -> str:
    out = write_html(runs, tmp_path / "report" / "index.html", extras)
    assert out.is_file()
    return out.read_text(encoding="utf-8")


def test_statuses_and_counts(tmp_path):
    page = _render(tmp_path)
    for status in ("passed", "unverified", "verified"):
        assert f'class="pill {status}"' in page
    assert "<b>3</b> quickstarts ran" in page
    assert "3/3" in page and "2/4" in page
    assert "First failed step 3" in page
    assert "beta init --project demo" in page
    assert "list price, not billed" in page


def test_patch_and_report_shown(tmp_path):
    page = _render(tmp_path)
    assert "gamma init demo" in page
    assert "was removed in 2.0" in page
    assert "Step 3 broke." in page


def test_missing_shown_when_extras_absent(tmp_path):
    page = _render(tmp_path)
    assert 'class="missing">missing<' in page
    assert page.count("missing</span>") >= 6


def test_a_trace_url_becomes_a_link_on_its_run(tmp_path):
    page = _render(tmp_path, {"trace_urls": {"run-verified": "https://us.cloud.langfuse.com/project/p/traces/abc"}})
    assert "https://us.cloud.langfuse.com/project/p/traces/abc" in page
    assert "Open trace" in page


def test_build_time_and_self_contained(tmp_path):
    page = _render(tmp_path)
    assert "Built 20" in page and "Z UTC" in page
    assert "<script" not in page.lower()
    assert not re.search(r"(src|href)=\"https?:", page.split("<body>")[0])
    assert "@import" not in page and "<link" not in page
    assert "__SUMMARY__" not in page and "__RUNS__" not in page


def test_html_escaping(tmp_path):
    runs = tmp_path / "runs"
    shutil.copytree(FIX / "run-failed", runs / "run-evil")
    sj = runs / "run-evil" / "state.json"
    rj = runs / "run-evil" / "runbook.json"
    evil = "<script>alert(1)</script>"
    sj.write_text(sj.read_text(encoding="utf-8").replace("beta init --project demo", evil), encoding="utf-8")
    rj.write_text(rj.read_text(encoding="utf-8").replace("beta init --project demo", evil), encoding="utf-8")
    page = _render(tmp_path, {"trace_urls": {"run-failed": "javascript:alert(1)"}}, runs)
    assert evil not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "javascript:" not in page


def test_empty_and_corrupt_runs(tmp_path):
    runs = tmp_path / "runs"
    (runs / "bad").mkdir(parents=True)
    (runs / "bad" / "state.json").write_text("{nope", encoding="utf-8")
    page = _render(tmp_path, runs=runs)
    assert "state.json unreadable" in page
    empty = _render(tmp_path / "e", runs=tmp_path / "nothing")
    assert "No runs found" in empty
