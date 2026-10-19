"""Receipts: price, tier caps, proof wording, and tamper detection. Offline."""

from __future__ import annotations

import json

from firstrun import receipt
from firstrun.models import Patch, RunState, RunStatus, StepStatus, Usage

ECON = {
    "generated_at": "2026-10-11T00:00:00Z",
    "margin_floor": 0.7,
    "drivers": {"compute_per_run": 0.002},
    "tiers": {
        "Free": {"cap_usd_per_run": 0.01},
        "Team": {"cap_usd_per_run": 0.05, "revenue_per_run": 0.2},
    },
}


def _state(status=RunStatus.VERIFIED, cost=0.04, patches=True) -> RunState:
    return RunState(
        run_id="20261011-000000-example", source_url="https://docs.example.com/start", status=status,
        step_status={1: StepStatus.PASSED, 2: StepStatus.PASSED},
        patches=[Patch(step_id=2, old_command="a \\\n| b", new_command="c", reason="x | y")] if patches else [],
        usage=Usage(input_tokens=1000, output_tokens=200, cost_usd=cost),
    )


def _run_dir(tmp_path, state):
    d = tmp_path / state.run_id
    d.mkdir()
    (d / "state.json").write_text(state.model_dump_json(), encoding="utf-8")
    (d / "report.md").write_text("# report\n", encoding="utf-8")
    return d


def test_caps_flag_a_run_over_a_tier(tmp_path):
    s = _state(cost=0.04)
    r = receipt.build(s, _run_dir(tmp_path, s), ECON, bills="team")
    free, team = r["caps"]
    assert not free["within_cap"] and free["margin_pct"] is None
    assert team["within_cap"] and team["bills_this_run"]
    assert team["used_pct"] == 80.0
    assert team["margin_pct"] == round(100 * (1 - (0.04 + 0.002) / 0.2), 1)


def test_proof_only_claims_what_ran(tmp_path):
    s = _state(status=RunStatus.UNVERIFIED)
    r = receipt.build(s, _run_dir(tmp_path, s), ECON)
    assert r["proof"]["verified"] is False and "Nothing here is verified" in r["proof"]["claim"]


def test_a_clean_first_pass_says_no_fix_was_needed(tmp_path):
    s = _state(status=RunStatus.PASSED, patches=False)
    assert "No fix was needed" in receipt.build(s, _run_dir(tmp_path, s), ECON)["proof"]["claim"]


def test_check_detects_an_edited_receipt_and_edited_evidence(tmp_path):
    s = _state()
    d = _run_dir(tmp_path, s)
    path = receipt.write(d, receipt.build(s, d, ECON))[0]
    assert receipt.check(path) == []
    edited = json.loads(path.read_text(encoding="utf-8"))
    edited["price"]["model_cost_usd"] = 0.001
    path.write_text(json.dumps(edited), encoding="utf-8")
    assert "edited" in receipt.check(path)[0]
    path.write_text(json.dumps(json.loads(json.dumps(edited)) | {"price": {**edited["price"], "model_cost_usd": 0.04}}), encoding="utf-8")
    (d / "report.md").write_text("# changed\n", encoding="utf-8")
    assert any("report.md changed" in p for p in receipt.check(path))


def test_markdown_patch_table_stays_one_line_per_row(tmp_path):
    s = _state()
    md = receipt.render_md(receipt.build(s, _run_dir(tmp_path, s), ECON))
    rows = [ln for ln in md.splitlines() if ln.startswith("| 2 |")]
    assert len(rows) == 1 and "\\|" in rows[0]


def _audit(cost=True) -> dict:
    a = {
        "id": "audit-20261011-000000-acme-widgets", "repo": "acme/widgets", "url": "https://github.com/acme/widgets",
        "docs_repo": "", "generated_at": "2026-10-11T00:00:00+00:00",
        "history": {"commits": 120, "since": "2026-01-01", "capped": False, "head": "abcdef1234567"},
        "summary": {"pages": 4, "fresh": 3, "aging": 0, "stale": 1, "quiet": 0, "features": 2, "uncovered": 1},
        "cards": [{"kind": "document", "evidence": [{"sha": "abc"}]}, {"kind": "automate", "evidence": []}],
        "jev": True,
    }
    if cost:
        a["cost"] = {"jev_calls": 2, "jev_input_tokens": 10_000, "jev_usd": 0.00042, "basis": "list price"}
    return a


def test_audit_receipt_prices_the_jev_calls_and_counts_cited_cards(tmp_path):
    (tmp_path / "audit.json").write_text("{}", encoding="utf-8")
    r = receipt.build_audit(_audit(), tmp_path)
    assert r["price"]["recorded"] and r["price"]["usd"] == 0.00042
    assert r["proof"]["cards_citing_evidence"] == 1 and not r["proof"]["all_cited"]
    assert "abcdef123" in r["proof"]["claim"]
    assert r["limits"]["dollar_cap_per_audit"] is None
    path = receipt.write(tmp_path, r, with_html=True)[0]
    assert receipt.check(path) == []
    (tmp_path / "audit.json").write_text('{"x":1}', encoding="utf-8")
    assert any("audit.json changed" in p for p in receipt.check(path))


def test_an_audit_without_cost_says_it_was_not_recorded(tmp_path):
    r = receipt.build_audit(_audit(cost=False), tmp_path)
    assert r["price"]["recorded"] is False and r["price"]["usd"] is None
    assert "not recorded" in receipt.render_audit_md(r)
    assert "Not recorded" in receipt.render_audit_html(r)


def test_jev_usage_counts_answered_calls_only():
    from firstrun import audit

    audit._JEV_USE.update(calls=0, input_tokens=0)
    audit._note_jev({"usage": {"input_tokens": 1000}})
    audit._note_jev({"answers": {}})
    c = audit.jev_cost()
    assert c["jev_calls"] == 2 and c["jev_input_tokens"] == 1000
    assert c["jev_usd"] == round(1000 * 0.042 / 1_000_000, 6)


# ----------------------------------------------------------------------------- the bill and the site copy

def _receipt(tmp_path, **kw):
    s = _state(**kw)
    return receipt.build(s, _run_dir(tmp_path, s), ECON, bills="team")


def test_bill_total_adds_model_usage_and_compute(tmp_path):
    r = _receipt(tmp_path, cost=0.0453)
    assert receipt.total_usd(r) == round(0.0453 + 0.002, 4)
    page = receipt.render_html(r)
    assert "$0.0453" in page and "$0.0020" in page and "$0.0473" in page
    assert "Verified" in page and "Billed tier" in page and "over cap" in page
    assert "firstrun receipt --check docs/receipts/FR-20261011-000000-example.json" in page
    assert "—" not in page and "–" not in page


def test_money_keeps_tiny_amounts_readable():
    assert receipt.money(0.0) == "$0.0000"
    assert receipt.money(0.000557) == "$0.000557"
    assert receipt.money(0.0453) == "$0.0453"
    assert receipt.money(None) == "Not recorded"


def test_bill_renders_when_optional_fields_are_missing():
    page = receipt.render_html({"receipt_id": "FR-x", "hash": "sha256:ab"})
    assert "Receipt" in page and "Not recorded" in page and "Not verified" in page
    audit_page = receipt.render_audit_html({"kind": "audit", "receipt_id": "FR-audit-x"})
    assert "Not recorded" in audit_page


def test_audit_bill_total_is_the_jev_cost_or_not_recorded():
    r = receipt.build_audit(_audit(), None)
    assert r["audit"]["evidence_sha256"] == {}
    assert receipt.total_usd(r) == 0.00042
    page = receipt.render_audit_html(r)
    assert "$0.000420" in page and "1 of 2 cards cited" in page
    old = receipt.build_audit(_audit(cost=False), None)
    assert receipt.total_usd(old) is None
    assert receipt.index_fields(old) == {"receipt": "FR-audit-20261011-000000-acme-widgets", "receipt_usd": None}


def test_publish_site_keeps_the_first_issue_time(tmp_path):
    r = _receipt(tmp_path)
    out = tmp_path / "receipts"
    receipt.publish_site({**r, "issued_at": "2026-01-01T00:00:00Z"}, out)
    receipt.publish_site(r, out)
    saved = json.loads((out / f"{r['receipt_id']}.json").read_text(encoding="utf-8"))
    assert saved["issued_at"] == "2026-01-01T00:00:00Z" and saved["hash"] == receipt.body_hash(saved)
    assert (out / f"{r['receipt_id']}.html").exists()
    assert receipt.billed_tier(out, r["receipt_id"]) == "Team"


def test_publish_all_covers_every_listed_run_and_audit(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    s = _state()
    d = _run_dir(runs, s)
    (d / "runbook.json").write_text("{", encoding="utf-8")  # unreadable runbook: steps fall back to the state
    docs = tmp_path / "docs"
    (docs / "runs").mkdir(parents=True)
    (docs / "audits").mkdir()
    (tmp_path / "business").mkdir()
    (tmp_path / "business" / "unit_economics.json").write_text(json.dumps(ECON), encoding="utf-8")
    redacted = "20261011-000000-exa[REDACTED]"
    (docs / "runs" / "index.json").write_text(json.dumps({"runs": [
        {"id": redacted, "url": s.source_url, "cost": 0.04}, {"id": "gone", "url": "x", "cost": 0}]}), encoding="utf-8")
    a = _audit(cost=False)
    (docs / "audits" / f"{a['id']}.json").write_text(json.dumps(a), encoding="utf-8")
    (docs / "audits" / "index.json").write_text(json.dumps({"audits": [{"id": a["id"]}]}), encoding="utf-8")
    done = receipt.publish_all(docs, runs)
    assert done["runs"] == 1 and done["audits"] == 1 and done["skipped"] == ["gone"]
    row = json.loads((docs / "runs" / "index.json").read_text(encoding="utf-8"))["runs"][0]
    assert row["receipt"] == f"FR-{s.run_id}" and row["receipt_usd"] == 0.042
    arow = json.loads((docs / "audits" / "index.json").read_text(encoding="utf-8"))["audits"][0]
    assert arow["receipt"] == f"FR-{a['id']}" and arow["receipt_usd"] is None
    assert (docs / "receipts" / f"FR-{a['id']}.html").exists()


def test_check_finds_the_evidence_in_the_run_folder(tmp_path, monkeypatch):
    from firstrun import config

    runs = tmp_path / "runs"
    runs.mkdir()
    s = _state()
    d = _run_dir(runs, s)
    path = receipt.publish_site(receipt.build(s, d, ECON), tmp_path / "docs" / "receipts")
    monkeypatch.setattr(config, "RUNS_DIR", runs)
    assert receipt.check(path) == []
    (d / "report.md").write_text("# changed\n", encoding="utf-8")
    assert any("report.md changed" in p for p in receipt.check(path))


def test_publishing_an_audit_writes_its_receipt(tmp_path):
    from firstrun import audit

    a = _audit()
    a.update({"summary": {**a["summary"], "oldest_days": 1, "median_age_days": 1, "cards": 2}, "release": {"name": ""}})
    audit.publish(a, tmp_path / "docs" / "audits")
    row = json.loads((tmp_path / "docs" / "audits" / "index.json").read_text(encoding="utf-8"))["audits"][0]
    assert row["receipt"] == f"FR-{a['id']}" and row["receipt_usd"] == 0.00042
    assert (tmp_path / "docs" / "receipts" / f"FR-{a['id']}.html").exists()


def test_an_estimated_audit_cost_is_labeled_everywhere(tmp_path):
    a = _audit()
    a["cost"] = {**a["cost"], "estimated": True, "basis": "Estimate. Re-run on 2026-10-11."}
    r = receipt.build_audit(a, tmp_path)
    assert r["price"]["estimated"] is True
    assert receipt.index_fields(r) == {"receipt": r["receipt_id"], "receipt_usd": 0.00042, "receipt_est": True}
    assert "Total (estimated)" in receipt.render_audit_html(r)
    assert "(estimated)" in receipt.render_audit_md(r)
    measured = receipt.build_audit(_audit(), tmp_path)
    assert measured["price"]["estimated"] is False and "receipt_est" not in receipt.index_fields(measured)
