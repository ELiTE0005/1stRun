"""publish: a finished run becomes a replay file and one row in the site log."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from firstrun import publish, share

FIXTURES = Path(__file__).parent / "fixtures_report"


def _run(tmp_path, name="run-verified") -> Path:
    dst = tmp_path / name
    shutil.copytree(FIXTURES / name, dst)
    return dst


def test_publish_writes_replay_and_row(tmp_path):
    site = tmp_path / "docs" / "runs"
    out = publish.publish_run(_run(tmp_path), site)
    doc = json.loads((site / "index.json").read_text(encoding="utf-8"))
    assert len(doc["runs"]) == 1
    row = doc["runs"][0]
    assert out == site / f"{row['id']}.txt"
    assert share.decode(out.read_text(encoding="utf-8"))["run_id"] == row["id"]
    assert row["total"] >= row["passed"]


def test_publish_twice_keeps_one_row(tmp_path):
    site = tmp_path / "runs"
    run = _run(tmp_path)
    publish.publish_run(run, site)
    publish.publish_run(run, site)
    assert len(json.loads((site / "index.json").read_text(encoding="utf-8"))["runs"]) == 1


def test_publish_off_site_is_a_no_op(tmp_path, monkeypatch):
    monkeypatch.delenv("FIRSTRUN_SITE_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    assert publish.publish_run(_run(tmp_path)) is None


def test_publish_all_skips_broken_folders(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    shutil.copytree(FIXTURES / "run-verified", runs / "good")
    (runs / "bad").mkdir()
    (runs / "bad" / "state.json").write_text("{", encoding="utf-8")
    (runs / "bad" / "runbook.json").write_text("{", encoding="utf-8")
    assert publish.publish_all(runs, tmp_path / "site") == 1


def test_publish_writes_the_receipt_when_the_plan_is_there(tmp_path):
    econ = {"generated_at": "x", "margin_floor": 0.7, "drivers": {"compute_per_run": 0.002},
            "tiers": {"Team": {"cap_usd_per_run": 0.05, "revenue_per_run": 0.2}}}
    (tmp_path / "business").mkdir()
    (tmp_path / "business" / "unit_economics.json").write_text(json.dumps(econ), encoding="utf-8")
    site = tmp_path / "docs" / "runs"
    publish.publish_run(_run(tmp_path), site)
    row = json.loads((site / "index.json").read_text(encoding="utf-8"))["runs"][0]
    assert row["receipt"] == f"FR-{row['id']}"
    assert row["receipt_usd"] == round(round(row["cost"], 4) + 0.002, 4)
    assert (tmp_path / "docs" / "receipts" / f"{row['receipt']}.html").exists()
