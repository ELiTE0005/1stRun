"""collect_evidence parsing and report extras loading. Offline."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from firstrun.report_html import load_evidence, write_html

spec = importlib.util.spec_from_file_location(
    "collect_evidence", Path(__file__).parent.parent / "scripts" / "collect_evidence.py")
ce = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ce)

TRACES = json.dumps({"data": {"traces": [
    {"traceName": "firstrun.run", "tags": ["v1"], "spansCount": 10, "toolCallsCount": 4, "totalCostUsd": 0.02,
     "durationMs": 20000, "status": "OK", "traceId": "a", "startedAt": "2026-10-10T07:40:00.000Z"},
    {"traceName": "firstrun.run", "tags": ["v1"], "spansCount": 20, "toolCallsCount": 6, "totalCostUsd": 0.04,
     "durationMs": 40000, "status": "ERROR", "traceId": "b", "startedAt": "2026-10-10T07:45:00.000Z"},
    {"traceName": "firstrun.run", "tags": [], "spansCount": 5, "toolCallsCount": 1, "totalCostUsd": 0,
     "durationMs": 1000, "status": "OK", "traceId": "c", "startedAt": "2026-10-10T08:00:00.000Z"},
    {"traceName": "doctor.probe.root", "tags": [], "traceId": "z", "startedAt": "2026-10-10T08:01:00.000Z"},
]}})


def test_group_runs():
    g = ce.group_runs(ce.parse_traces(TRACES))
    assert set(g) == {"v1", "dev"}
    assert g["v1"]["count"] == 2 and g["v1"]["errors"] == 1
    assert g["v1"]["avg_spans"] == 15 and g["v1"]["avg_tool_calls"] == 5
    assert g["v1"]["avg_duration_s"] == 30
    lo, hi = ce.windows(g)["v1"]
    assert lo < "2026-10-10T07:40:00Z" and hi > "2026-10-10T07:45:00Z"


def test_entire_parsers():
    cps = "  branch       main\n  checkpoints  13\n\n● abc  [temporary]  x\n● 01M4JEKV31HHMN7SCZ1T02XMD3  \"q\"\n"
    assert ce.parse_checkpoint_count(cps) == 13
    assert ce.parse_latest_checkpoint(cps) == "01M4JEKV31HHMN7SCZ1T02XMD3"
    assert ce.parse_graph_savings("ESTIMATED SAVINGS  ~19,315 tokens  (~0.03%)") == 19315
    assert ce.parse_graph_savings("nothing") is None


def test_load_evidence_and_render(tmp_path):
    runs = Path(__file__).parent / "fixtures_report"
    ev = tmp_path / "evidence"
    ev.mkdir()
    g = ce.group_runs(ce.parse_traces(TRACES))
    g["v2"] = dict(g["v1"], avg_tool_calls=2.0)
    (ev / "neatlogs_runs.json").write_text(json.dumps({"groups": g}), encoding="utf-8")
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
