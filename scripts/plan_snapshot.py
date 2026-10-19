"""Write docs/data/plan.json, the data behind the site's /plan/ page.

It joins three sources so one file shows the whole loop:
- business/unit_economics.json, from `firstrun econ` (neatlogs traces -> cost per run -> tier caps)
- the cfo.ai model links and the month-18 cash per Scenario, read from cfo.ai on the date in `cfo.read_at`
- neatlogs alert history for the cost guardrails, read with the neatlogs CLI

Run it after `firstrun econ`:  python scripts/plan_snapshot.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ECON = ROOT / "business" / "unit_economics.json"
CFO_MODEL = ROOT / "docs" / "data" / "cfo-model.json"
OUT = ROOT / "docs" / "data" / "plan.json"
GUARDRAILS = ("firstrun p95 run cost above Scale cap", "firstrun budget guardrail tripped")

CFO = {
    "model": "https://cfo.ai/s/_u5lbrHIl9KX_JQE",
    "drivers": "https://app.cfo.ai/s/p_AQL4owYkMGMxN2NhMTMtOGRiNy00NDJjLWEwYzYtMTUwOGJkZDZkNTNlDWRlZmF1bHRfbGF5ZXI",
    "assumptions": "https://app.cfo.ai/s/p_AQL4owYkYjAzNWE5ZmMtNDg2Yy00MzljLWIwNDMtMmUxMmJhMTE3MDM5DWRlZmF1bHRfbGF5ZXI",
    "comparison": "https://app.cfo.ai/s/p_AQL4owYkYTM1ZDJjZmItYmZhMy00NjE5LWI5YTYtZmVmODE4MjMwZGMwDWRlZmF1bHRfbGF5ZXI",
}


def alerts() -> list[dict]:
    """Fires of the two cost guardrails. Empty when the neatlogs CLI is not reachable."""
    npx = shutil.which("npx")
    if not npx:
        return []
    p = subprocess.run([npx, "-y", "neatlogs-cli", "alerts", "history", "--json"], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=180)
    try:
        rows = json.loads(p.stdout)["data"]["alertHistory"]
    except (ValueError, KeyError, TypeError):
        return []
    out = []
    for r in rows:
        if r.get("ruleName") in GUARDRAILS:
            t = r.get("investigationTarget") or {}
            out.append({"rule": r["ruleName"], "fired_at": r.get("firedAt", ""), "trace_id": t.get("traceId", ""),
                        "window_minutes": r.get("windowMinutes")})
    return sorted(out, key=lambda a: a["fired_at"], reverse=True)


def main() -> None:
    econ = json.loads(ECON.read_text(encoding="utf-8"))
    cfo = json.loads(CFO_MODEL.read_text(encoding="utf-8"))
    month18 = {name: s["cash"][-1] for name, s in cfo["scenarios"].items()}
    doc = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "econ_generated_at": econ["generated_at"],
        "margin_floor": econ["margin_floor"],
        "drivers": econ["drivers"],
        "tiers": econ["tiers"],
        "cfo": {**CFO, "source": cfo["source"], "last_month": cfo["months"][-1], "cash_last_month": month18},
        "alerts": alerts(),
    }
    OUT.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(doc['tiers'])} tiers, {len(doc['alerts'])} guardrail fires")


if __name__ == "__main__":
    main()
