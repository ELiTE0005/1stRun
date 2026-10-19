"""Estimate the Jev cost of audits that ran before cost tracking, by re-running each one today.

An audit board in docs/audits/<id>.json that has no `cost` gets one, marked `estimated`. The numbers
come from a real re-run of the same audit (same repo, same docs repo), so they are measured Jev usage
for an equivalent audit, not a guess. The re-run publishes nothing: it only reads the cost counters.

    python scripts/audit_cost_estimates.py            # print what would be measured
    python scripts/audit_cost_estimates.py --apply    # re-run, write cost into the boards, then
                                                      # run `firstrun receipt --all-published`

Needs git, network and TYPESAFE_API_KEY (read from .env in the folder you run it from).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from firstrun import audit as audit_mod  # noqa: E402

SITE = ROOT / "docs" / "audits"


def basis(today: str) -> str:
    return (f"Estimate. This audit ran before cost tracking. Re-running the same audit on {today} used this much Jev "
            "input, billed at TypeSafe's list price of $0.042 per million input tokens. Output is free, and the clone "
            "and the analysis are free.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Re-run the audits and write the estimates.")
    args = ap.parse_args()
    todo = []
    for p in sorted(SITE.glob("audit-*.json")):
        board = json.loads(p.read_text(encoding="utf-8"))
        if not board.get("cost"):
            todo.append((p, board))
    for p, b in todo:
        print(f"{'measure' if args.apply else 'would measure'} {b['repo']}" + (f" (docs in {b['docs_repo']})" if b.get("docs_repo") else ""))
    if not args.apply or not todo:
        print("dry run. Add --apply to re-run and write." if not args.apply else "nothing to estimate.")
        return 0
    today = date.today().isoformat()
    for p, b in todo:
        audit_mod._JEV_USE.update(calls=0, input_tokens=0)
        audit_mod.audit(b["repo"], stale_days=b.get("stale_days", 180), use_jev=True, docs_repo=b.get("docs_repo") or None)
        c = audit_mod.jev_cost()
        if not c["jev_calls"]:
            print(f"  {b['repo']}: Jev made no call, so no estimate was written (is TYPESAFE_API_KEY set?)")
            continue
        b["cost"] = {**c, "estimated": True, "basis": basis(today)}
        p.write_text(json.dumps(b, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
        print(f"  {b['repo']}: {c['jev_calls']} calls, {c['jev_input_tokens']:,} tokens, ${c['jev_usd']:.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
