import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("neatlogs_issues", Path(__file__).resolve().parents[1] / "scripts" / "neatlogs_issues.py")
ni = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ni)


def test_detection_body_counts_spans_and_traces():
    det = {"id": "d1", "displayName": "docs step broke", "type": "regex", "threshold": 0.5, "groupName": "Negative"}
    hits = [{"traceId": "t1", "detectedAt": "2026-10-10T12:00:00Z"}, {"traceId": "t1", "detectedAt": "2026-10-10T12:05:00Z"},
            {"traceId": "t2", "detectedAt": "2026-10-10T17:00:00Z"}]
    body = ni.body_for_detection(det, hits, "2026-10-04")
    assert body.startswith(ni.MARK)
    assert "**3 spans in 2 traces**" in body
    assert body.index("`t2`") < body.index("`t1`")  # newest trace first
    assert "Fixes #" in body


def test_guardrail_body_names_the_plan_page():
    fires = [{"firedAt": "2026-10-11T01:31:19Z", "investigationTarget": {"kind": "trace_search"}},
             {"firedAt": "2026-10-10T17:40:13Z", "investigationTarget": {"traceId": "abc"}}]
    body = ni.body_for_guardrail("firstrun budget guardrail tripped", fires)
    assert "fired **2 times**" in body and "`abc`" in body and "/plan/" in body
