"""The report page reads the evidence files that exist and skips the ones that do not. Offline."""

from __future__ import annotations

import json
from pathlib import Path

from firstrun.report_html import load_evidence, write_html

GROUP = {"count": 2, "errors": 1, "avg_spans": 15, "avg_tool_calls": 5, "avg_cost_usd": 0.03, "avg_duration_s": 30,
         "traces": [{"traceId": "a", "startedAt": "2026-10-10T07:40:00.000Z", "status": "OK"}]}


def test_load_evidence_and_render(tmp_path):
    runs = Path(__file__).parent / "fixtures_report"
    ev = tmp_path / "evidence"
    ev.mkdir()
    groups = {"v1": GROUP, "v2": dict(GROUP, avg_tool_calls=2.0)}
    (ev / "neatlogs_runs.json").write_text(json.dumps({"groups": groups}), encoding="utf-8")
    (ev / "entire.json").write_text(json.dumps({"checkpoints": 15, "graph_tokens_saved": 19315}), encoding="utf-8")
    extras = load_evidence(ev, runs)
    assert extras["entire_checkpoints"] == 15
    assert extras["neatlogs_summary"] == "5 vs 2 tool calls"
    page = write_html(runs, tmp_path / "index.html", extras).read_text(encoding="utf-8")
    assert 'title="source: evidence/entire.json"' in page
    assert 'title="source: evidence/neatlogs_runs.json"' in page
    assert "19,315" in page


def test_load_evidence_missing_dir(tmp_path):
    extras = load_evidence(tmp_path / "none", tmp_path)
    assert "neatlogs_groups" not in extras
