"""Publish a run to the public site log: docs/runs/<run id>.txt, one row in docs/runs/index.json, and its receipt.

The repo is public and Netlify serves docs/, so a committed row is a run anyone can replay.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from firstrun import share

INDEX = "index.json"


def find_site_dir(start: Path | None = None) -> Path | None:
    """docs/runs of the firstrun checkout. FIRSTRUN_SITE_DIR wins, then the cwd and its parents."""
    env = os.environ.get("FIRSTRUN_SITE_DIR")
    if env:
        p = Path(env)
        return p if p.is_dir() else None
    here = (start or Path.cwd()).resolve()
    for base in [here, *here.parents]:
        cand = base / "docs" / "runs"
        if (cand / INDEX).exists():
            return cand
    return None


def _first_error(step: dict) -> str:
    lines = [ln.strip() for ln in (step.get("error_tail") or "").splitlines() if ln.strip()]
    if not lines:
        return ""
    bad = [ln for ln in lines if re.search(r"error|not found|no module|cannot|can't|failed|denied|timed out|exit", ln, re.I)]
    return bad[-1][:140] if bad else ""


def _summary(p: dict) -> str:
    steps = p["steps"]
    skipped = [s for s in steps if s["skipped"]]
    ran = [s for s in steps if not s["skipped"]]
    failed = [s for s in ran if s["status"] in ("failed", "gave_up", "needs_human")]
    if not steps:
        return "Stopped before any step ran."
    if failed:
        s = failed[0]
        err = _first_error(s)
        return f"Step {s['id']} broke: {s['intent']}." + (f" {err}" if err else "")
    bits = [f"{sum(1 for s in ran if s['status'] == 'passed')} of {len(ran)} runnable steps passed."]
    if p["patches"]:
        bits.append(f"{len(p['patches'])} fix{'es' if len(p['patches']) != 1 else ''} proven in a fresh container.")
    if skipped:
        bits.append(f"{len(skipped)} skipped: {skipped[0]['skip_reason'].rstrip('.')}.")
    return " ".join(bits)


def _cost(run_dir: Path) -> float:
    """List-price model cost in dollars, to 4 places. The share payload rounds to cents."""
    try:
        return round(float(json.loads((run_dir / "state.json").read_text(encoding="utf-8"))["usage"]["cost_usd"]), 4)
    except (OSError, ValueError, KeyError, TypeError):
        return 0.0


def row_for(payload: dict, cost: float | None = None) -> dict:
    counted = [s for s in payload["steps"] if not s["skipped"]]
    ver = payload["verify"]
    return {
        "id": payload["run_id"],
        "ts": payload.get("started_at") or "",
        "target": payload["target"],
        "title": payload["title"] or payload["target"],
        "url": payload["source_url"],
        "status": payload["status"],
        "passed": ver["steps_passed"],
        "total": len(payload["steps"]),
        "runnable": len(counted),
        "skipped": len(payload["steps"]) - len(counted),
        "fixes": len(payload["patches"]),
        "seconds": round(payload.get("time_to_first_success_s") or 0),
        "cost": payload.get("cost_usd", 0) if cost is None else cost,
        "fixture": bool(payload.get("fixture")),
        "summary": _summary(payload),
    }


def _receipt(run_dir: Path, site: Path, run_id: str) -> dict:
    """Write the run's receipt into docs/receipts. Returns the index fields, or nothing when it cannot be built."""
    from firstrun import receipt

    docs = site.parent
    econ, cfo = receipt.load_econ(docs)
    if econ is None:
        return {}
    try:
        out = docs / "receipts"
        r = receipt.for_run(run_dir, econ, receipt.billed_tier(out, f"FR-{run_id}"), cfo)
        receipt.publish_site(r, out)
        return receipt.index_fields(r)
    except Exception:  # noqa: BLE001 - a receipt failure never blocks the run log
        return {}


def publish_run(run_dir, site_dir: Path | None = None) -> Path | None:
    """Write the replay file and upsert the index row. Returns the replay file, or None off-site."""
    site = site_dir or find_site_dir()
    if site is None:
        return None
    run_dir = Path(run_dir)
    payload = share.build_payload(run_dir)
    run_id = payload["run_id"]
    site.mkdir(parents=True, exist_ok=True)
    out = site / f"{run_id}.txt"
    out.write_text(share.encode(payload) + "\n", encoding="utf-8")
    idx_path = site / INDEX
    try:
        doc = json.loads(idx_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = {}
    rows = [r for r in doc.get("runs", []) if r.get("id") != run_id]
    row = row_for(payload, _cost(run_dir))
    row.update(_receipt(run_dir, site, run_id))
    rows.append(row)
    rows.sort(key=lambda r: r.get("ts", ""), reverse=True)
    idx_path.write_text(json.dumps({"runs": rows}, indent=1) + "\n", encoding="utf-8")
    return out


def publish_all(runs_dir, site_dir: Path | None = None) -> int:
    """Backfill every finished run folder. Returns how many were published."""
    n = 0
    for d in sorted(Path(runs_dir).glob("*")):
        if (d / "state.json").exists() and (d / "runbook.json").exists():
            try:
                if publish_run(d, site_dir):
                    n += 1
            except Exception:  # noqa: BLE001 - one broken run folder never stops the backfill
                continue
    return n
