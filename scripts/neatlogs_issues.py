"""Turn neatlogs detections and cost-guardrail alerts into GitHub issues on this repo.

One issue per FirstRun detection with hits in the window, plus one per cost guardrail that fired.
Each issue lists the traces neatlogs flagged, so the fix PR can say `Fixes #N` and the loop
closes on GitHub. A trace carries no FirstRun run id, so the issue links traces, not replays. Re-running refreshes the
issues, and closes one whose detection had no hit in the window.

    python scripts/neatlogs_issues.py            # print what would change
    python scripts/neatlogs_issues.py --apply    # create, update or close the issues

Needs the neatlogs CLI (npx neatlogs-cli, logged in or NEATLOGS_API_KEY) and gh.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = "HighnessAtharva/firstrun"
LABEL = "neatlogs"
SITE = "https://firstrun.atharvashah.com"
# The detections FirstRun added for its own traces, plus the built-in failure detection it relies on.
WATCH = ("docs step broke", "planner invented a step", "Budget Limit Exceeded Alert", "Missing API Key Detector",
         "Documentation Unreachable Alert", "Verification Error Monitor", "Prerequisite Validation Error Monitor",
         "Execution Failed")
GUARDRAILS = ("firstrun p95 run cost above Scale cap", "firstrun budget guardrail tripped")
# These hits show FirstRun working as designed: it caught broken docs in the pages it tested, or a guardrail
# stopped a run. They stay in neatlogs for review, but no issue is opened for them. An open one is closed.
EXPECTED = ("docs step broke", "Execution Failed", "Prerequisite Validation Error Monitor",
            "Documentation Unreachable Alert", "Verification Error Monitor", "Missing API Key Detector",
            "Budget Limit Exceeded Alert")
EXPECTED_GUARDRAILS = ("firstrun budget guardrail tripped",)
# Hits before these times came from a detection that was wrong. "planner invented a step" matched the docs text
# the planner echoes back, until its regex was narrowed to each step's command field on 2026-10-11.
# That update re-scored 5 older spans at 06:08 UTC, so the floor sits after it.
COUNT_FROM = {"planner invented a step": "2026-10-11T06:10:00Z"}
MARK = "<!-- neatlogs-issues -->"


def nl(*args: str) -> dict:
    npx = shutil.which("npx") or "npx"
    p = subprocess.run([npx, "-y", "neatlogs-cli", *args, "--json"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=240)
    try:
        return json.loads(p.stdout).get("data") or {}
    except ValueError:
        raise SystemExit(f"neatlogs {' '.join(args)} failed: {(p.stderr or p.stdout)[:300]}")


def gh(*args: str, stdin: str | None = None) -> str:
    p = subprocess.run(["gh", *args], input=stdin, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise SystemExit(f"gh {' '.join(args[:3])} failed: {p.stderr.strip()[:300]}")
    return p.stdout




def body_for_detection(det: dict, hits: list[dict], since: str) -> str:
    traces: dict[str, list[dict]] = {}
    for h in hits:
        traces.setdefault(h["traceId"], []).append(h)
    rows = []
    for tid, hs in sorted(traces.items(), key=lambda kv: max(h["detectedAt"] for h in kv[1]), reverse=True)[:12]:
        rows.append(f"| `{tid}` | {len(hs)} | {max(h['detectedAt'] for h in hs)[:16].replace('T', ' ')} UTC |")
    first = min(h["detectedAt"] for h in hits)[:10]
    last = max(h["detectedAt"] for h in hits)[:10]
    return "\n".join([
        MARK,
        f"neatlogs flagged **{len(hits)} spans in {len(traces)} traces** for the detection `{det['displayName']}` "
        f"between {first} and {last}.",
        "",
        "| Trace | Spans | Last hit |",
        "|---|---|---|",
        *rows,
        "",
        f"Showing the 12 newest traces. Detection `{det['id']}`, type {det.get('type')}, threshold {det.get('threshold')}, group {det.get('groupName')}.",
        "",
        "**Next step.** Open a trace in neatlogs (project firstrun) and run Investigate. Fix the cause, "
        "then write `Fixes #<this issue>` in the PR so the issue closes with the fix.",
        "",
        f"Written by `scripts/neatlogs_issues.py` from neatlogs data since {since}. Run it again to refresh this issue. "
        "It closes the issue once the detection has no hit in the window.",
    ])


def body_for_guardrail(rule: str, fires: list[dict]) -> str:
    rows = [f"| {f['firedAt'][:16].replace('T', ' ')} UTC | "
            + (f"`{f['investigationTarget']['traceId']}`" if (f.get("investigationTarget") or {}).get("traceId") else "24 h window")
            + " |" for f in fires]
    return "\n".join([
        MARK,
        f"The neatlogs alert rule `{rule}` fired **{len(fires)} times**. Its threshold is the Scale tier cap that "
        f"the cfo.ai plan sets, so a fire means real runs cost more than the plan allows.",
        "",
        "| Fired | Target |",
        "|---|---|",
        *rows,
        "",
        f"**Next step.** Run `firstrun econ` to re-measure cost per run, update the cfo.ai drivers, then "
        f"`python scripts/plan_snapshot.py`. The current caps and margins are on {SITE}/plan/.",
        "",
        "Written by `scripts/neatlogs_issues.py` from the neatlogs alert history.",
    ])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Write to GitHub. Without it, print the plan.")
    ap.add_argument("--days", type=int, default=7, help="Hit window in days.")
    a = ap.parse_args()
    since_dt = datetime.now(timezone.utc) - timedelta(days=a.days)
    since = since_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    wanted: dict[str, tuple[str, str]] = {}  # title -> (body, "open"|"close")
    for det in nl("detections", "list")["detections"]:
        if det["displayName"] not in WATCH or not det.get("isActive") or det["displayName"] in EXPECTED:
            continue
        floor = max(since, COUNT_FROM.get(det["displayName"], ""))
        hits = [h for h in nl("detections", "hits", det["id"], "--all", "--max-items", "500").get("hits", [])
                if h.get("detectedAt", "") >= floor]
        title = f"neatlogs detection: {det['displayName']}"
        wanted[title] = (body_for_detection(det, hits, since[:10]), "open") if hits else ("", "close")
    fires: dict[str, list[dict]] = {}
    for f in nl("alerts", "history").get("alertHistory", []):
        if f.get("ruleName") in GUARDRAILS and f.get("ruleName") not in EXPECTED_GUARDRAILS and f.get("firedAt", "") >= since:
            fires.setdefault(f["ruleName"], []).append(f)
    for rule, fs in fires.items():
        wanted[f"neatlogs alert: {rule}"] = (body_for_guardrail(rule, fs), "open")
    for name in EXPECTED:
        wanted[f"neatlogs detection: {name}"] = ("", "expected")
    for rule in EXPECTED_GUARDRAILS:
        wanted[f"neatlogs alert: {rule}"] = ("", "expected")

    existing = {i["title"]: i for i in json.loads(gh("issue", "list", "-R", REPO, "--label", LABEL, "--state", "all",
                                                       "--limit", "100", "--json", "number,title,state"))}
    if a.apply:
        gh("label", "create", LABEL, "-R", REPO, "--color", "5319e7", "--force",
           "--description", "Opened from neatlogs detections and alerts")
    for title, (body, want) in wanted.items():
        cur = existing.get(title)
        if want == "expected":
            if cur and cur["state"] == "OPEN":
                print(f"close  #{cur['number']} {title} (expected behavior)")
                if a.apply:
                    gh("issue", "close", str(cur["number"]), "-R", REPO, "--comment",
                       "Expected behavior: FirstRun caught broken docs in a page it tested, or a guardrail stopped a run. "
                       "The hits stay in neatlogs. scripts/neatlogs_issues.py no longer opens an issue for this one.")
            continue
        if want == "close":
            if cur and cur["state"] == "OPEN":
                print(f"close  #{cur['number']} {title}")
                if a.apply:
                    gh("issue", "close", str(cur["number"]), "-R", REPO, "--comment",
                       f"No counted neatlogs hit in the last {a.days} days. Closed by scripts/neatlogs_issues.py.")
            continue
        if cur:
            print(f"update #{cur['number']} {title}")
            if a.apply:
                gh("issue", "edit", str(cur["number"]), "-R", REPO, "--body-file", "-", stdin=body)
                if cur["state"] != "OPEN":
                    gh("issue", "reopen", str(cur["number"]), "-R", REPO)
        else:
            print(f"create {title}")
            if a.apply:
                print("  " + gh("issue", "create", "-R", REPO, "--title", title, "--label", LABEL,
                                "--body-file", "-", stdin=body).strip())
    if not a.apply:
        print("dry run. Add --apply to write.")


if __name__ == "__main__":
    main()
