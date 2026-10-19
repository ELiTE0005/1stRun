"""Collect the evidence the report page reads into evidence/*.json. Rerunnable.

    python scripts/collect_evidence.py [--from 2026-10-01T00:00:00Z]

Writes evidence/neatlogs_runs.json, evidence/neatlogs_analytics_<tag>.json,
evidence/entire.json and evidence/graph.ndjson. Keys are read from .env, never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "evidence"
NEATLOGS = ["npx", "--yes", "-p", "node@22", "-p", "neatlogs-cli@0.2.0", "--", "neatlogs"]


def _run(cmd: list[str], env: dict | None = None, timeout: int = 180) -> tuple[int, str, str]:
    exe = shutil.which(cmd[0]) or cmd[0]
    try:
        p = subprocess.run([exe, *cmd[1:]], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=env, timeout=timeout, cwd=ROOT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", f"{type(exc).__name__}: {exc}"
    return p.returncode, p.stdout, p.stderr


def _env() -> dict:
    sys.path.insert(0, str(ROOT / "src"))
    try:
        from firstrun.config import load_env

        load_env()
    except Exception:  # noqa: BLE001
        pass
    return dict(os.environ)


def _parse_ts(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- neatlogs ---------------------------------------------------------------

def parse_traces(text: str) -> list[dict]:
    """Return the trace dicts of a `neatlogs traces list --json` payload."""
    data = json.loads(text)
    return list(((data.get("data") or {}).get("traces")) or [])


def group_runs(traces: list[dict]) -> dict[str, dict]:
    """Keep traceName == firstrun.run, group by the first tag (no tag means dev)."""
    buckets: dict[str, list[dict]] = {}
    for t in traces:
        if t.get("traceName") != "firstrun.run":
            continue
        tag = (t.get("tags") or ["dev"])[0]
        buckets.setdefault(tag, []).append(t)

    def avg(items, key):
        vals = [float(i.get(key) or 0) for i in items]
        return round(sum(vals) / len(vals), 4) if vals else 0.0

    out = {}
    for tag, items in buckets.items():
        items = sorted(items, key=lambda t: t.get("startedAt") or "")
        out[tag] = {
            "count": len(items),
            "avg_spans": avg(items, "spansCount"),
            "avg_tool_calls": avg(items, "toolCallsCount"),
            "avg_cost_usd": avg(items, "totalCostUsd"),
            "avg_duration_s": round(avg(items, "durationMs") / 1000, 1),
            "errors": sum(1 for i in items if i.get("status") == "ERROR"),
            "traces": [{"traceId": i.get("traceId"), "startedAt": i.get("startedAt"),
                        "status": i.get("status")} for i in items],
        }
    return out


def windows(groups: dict[str, dict]) -> dict[str, tuple[str, str]]:
    """Per tag, (from, to) from the traces' startedAt min and max. `to` is exclusive, so add 61 s."""
    res = {}
    for tag, g in groups.items():
        stamps = [_parse_ts(t["startedAt"]) for t in g["traces"] if t.get("startedAt")]
        if stamps:
            res[tag] = (_iso(min(stamps) - timedelta(seconds=1)), _iso(max(stamps) + timedelta(seconds=61)))
    return res


def _neatlogs(args: list[str], env: dict) -> tuple[int, str, str]:
    rc, out, err = _run([*NEATLOGS, *args], env=env)
    if rc != 0 and "NEATLOGS_API_KEY" in env:
        clean = {k: v for k, v in env.items() if k != "NEATLOGS_API_KEY"}
        rc2, out2, err2 = _run([*NEATLOGS, *args], env=clean)
        if rc2 == 0:
            return rc2, out2, err2
    return rc, out, err


def collect_neatlogs(since: str, env: dict) -> dict[str, dict]:
    rc, out, err = _neatlogs(["traces", "list", "--from", since, "--all", "--max-items", "300",
                              "--limit", "50", "--json"], env)
    if rc != 0:
        print(f"neatlogs traces list failed: {err.strip()[:300]}")
        return {}
    groups = group_runs(parse_traces(out))
    payload = {"generated_at": _iso(datetime.now(timezone.utc)), "from": since, "groups": groups}
    (EVIDENCE / "neatlogs_runs.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    for tag, (lo, hi) in windows(groups).items():
        result = {"tag": tag, "from": lo, "to": hi}
        for name in ("kpis", "cost"):
            rc, out, err = _neatlogs(["analytics", name, "--from", lo, "--to", hi,
                                      "--workflow", "firstrun", "--json"], env)
            if rc == 0:
                try:
                    result[name] = json.loads(out)
                    continue
                except ValueError:
                    pass
            result[name] = {"error": (err or out).strip()[:500]}
        (EVIDENCE / f"neatlogs_analytics_{tag}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return groups


# --- Entire -----------------------------------------------------------------

def parse_checkpoint_count(text: str) -> int | None:
    m = re.search(r"^\s*checkpoints\s+(\d+)", text, re.M | re.I)
    return int(m.group(1)) if m else None


def parse_latest_checkpoint(text: str) -> str | None:
    """First 26-character checkpoint id in the list. Temporary session rows are skipped."""
    m = re.search(r"^\S*\s*([0-9A-Z]{26})\b", text, re.M)
    return m.group(1) if m else None


def parse_graph_savings(text: str) -> int | None:
    m = re.search(r"ESTIMATED SAVINGS\s+~?([\d,]+)\s+tokens", text)
    return int(m.group(1).replace(",", "")) if m else None


def collect_entire() -> dict:
    status = _run(["entire", "status"])
    cps = _run(["entire", "checkpoint", "list"])
    stats = _run(["entire", "graph", "stats", "--repo", "."])
    data = {
        "generated_at": _iso(datetime.now(timezone.utc)),
        "checkpoints": parse_checkpoint_count(cps[1]),
        "latest_checkpoint": parse_latest_checkpoint(cps[1]),
        "graph_tokens_saved": parse_graph_savings(stats[1]),
        "raw": {"status": status[1] or status[2], "checkpoint_list": cps[1] or cps[2],
                "graph_stats": stats[1] or stats[2]},
    }
    (EVIDENCE / "entire.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    rc, out, err = _run(["entire", "graph", "snapshot", "--repo", ".", "--format", "ndjson"], timeout=600)
    if rc == 0:
        (EVIDENCE / "graph.ndjson").write_text(out, encoding="utf-8")
    else:
        print(f"entire graph snapshot failed: {err.strip()[:300]}")
    return data


def main() -> int:
    ap = argparse.ArgumentParser(description="Collect report evidence into evidence/.")
    ap.add_argument("--from", dest="since", default="2026-10-01T00:00:00Z")
    args = ap.parse_args()
    EVIDENCE.mkdir(exist_ok=True)
    groups = collect_neatlogs(args.since, _env())
    for tag, g in groups.items():
        print(f"neatlogs {tag}: {g['count']} runs, {g['errors']} errors")
    entire = collect_entire()
    print(f"entire: {entire['checkpoints']} checkpoints, graph saved {entire['graph_tokens_saved']} tokens")
    return 0


if __name__ == "__main__":
    sys.exit(main())
