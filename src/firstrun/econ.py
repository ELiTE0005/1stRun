"""Unit economics from run folders, and the per-tier cost cap the agent enforces.

`firstrun econ` reads every run folder's state.json, writes business/drivers.csv for cfo.ai,
and writes business/unit_economics.json. `firstrun run --tier NAME` reads that file and
stops a run whose spend passes the tier's cap.
"""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from firstrun import config
from firstrun.models import Budget

BUSINESS = Path(os.environ.get("FIRSTRUN_BUSINESS_DIR", "business"))
DEFAULT_MARGIN_FLOOR = 0.70


class EconError(Exception):
    pass


def _parse_time(text: str) -> datetime | None:
    try:
        t = datetime.fromisoformat((text or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def fetch_traces(since: str, runs_dir: Path | None = None) -> str:
    """One record per finished run folder since `since`, in the payload shape `run_traces` reads.

    The cost is the list price FirstRun kept in state.json, the same number a tier's cap is checked against.
    """
    floor = _parse_time(since) or datetime.min.replace(tzinfo=timezone.utc)
    traces = []
    for path in sorted((runs_dir or config.RUNS_DIR).glob("*/state.json")):
        try:
            st = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        began, ended = _parse_time(st.get("started_at", "")), _parse_time(st.get("finished_at", ""))
        if not began or not ended or began < floor:
            continue
        traces.append({"traceName": "firstrun.run", "traceId": st.get("run_id", path.parent.name),
                       "totalCostUsd": float((st.get("usage") or {}).get("cost_usd") or 0),
                       "durationMs": max((ended - began).total_seconds(), 0) * 1000})
    return json.dumps({"data": {"traces": traces}})


def run_traces(text: str) -> list[dict]:
    """The `firstrun.run` records of a `fetch_traces` payload."""
    data = json.loads(text)
    traces = ((data.get("data") or {}).get("traces")) or []
    return [t for t in traces if t.get("traceName") == "firstrun.run"]


def _pick(values: list[float], q: float) -> float:
    """Nearest-rank quantile. Values must be sorted."""
    return values[round(q * (len(values) - 1))]


def drivers(traces: list[dict], vm_price_per_hour: float) -> dict:
    """Measured cost and duration per run, with the trace behind each quantile."""
    if not traces:
        raise EconError("no firstrun.run traces to measure")
    by_cost = sorted(traces, key=lambda t: float(t.get("totalCostUsd") or 0))
    costs = [float(t.get("totalCostUsd") or 0) for t in by_cost]
    secs = [float(t.get("durationMs") or 0) / 1000 for t in traces]
    mean_s = sum(secs) / len(secs)

    def at(q: float) -> dict:
        t = by_cost[round(q * (len(by_cost) - 1))]
        return {"usd": round(float(t.get("totalCostUsd") or 0), 5), "trace_id": t.get("traceId", "")}

    return {
        "traces": len(traces),
        "cost_mean": round(sum(costs) / len(costs), 5),
        "cost_p50": at(0.50),
        "cost_p90": at(0.90),
        "cost_p95": at(0.95),
        "cost_max": at(1.0),
        "duration_mean_s": round(mean_s, 1),
        "compute_per_run": round(vm_price_per_hour * mean_s / 3600, 5),
        "vm_price_per_hour": vm_price_per_hour,
    }


def tier_caps(d: dict, tiers: dict, margin_floor: float, costs: list[float]) -> dict:
    """Per tier: the model spend one run may use and still keep the margin floor.

    A run that hits the cap every time still earns the floor, so the floor holds in the
    worst month. A tier with no revenue gets the measured median as its cap.
    """
    compute = d["compute_per_run"]
    costs = sorted(costs)
    out = {}
    for name, tier in tiers.items():
        price, runs = float(tier["price_usd_month"]), int(tier["runs_per_month"])
        if price <= 0 or runs <= 0:
            cap = d["cost_p50"]["usd"]
            rule = "no revenue, so the cap is the measured median run"
        else:
            cap = round(price / runs * (1 - margin_floor) - compute, 5)
            rule = f"revenue per run x (1 - {margin_floor:.2f}) - compute"
        over = sum(1 for c in costs if c > cap)
        row = {
            "price_usd_month": price,
            "runs_per_month": runs,
            "cap_usd_per_run": max(cap, 0.0),
            "cap_rule": rule,
            "measured_runs_over_cap_pct": round(100 * over / len(costs), 1),
        }
        if price > 0:
            rev = price / runs
            p95 = d["cost_p95"]["usd"] + compute
            row.update({
                "revenue_per_run": round(rev, 5),
                "margin_at_mean_pct": round(100 * (1 - (d["cost_mean"] + compute) / rev), 1),
                "margin_at_p95_pct": round(100 * (1 - p95 / rev), 1),
                "margin_at_old_cap_pct": round(100 * (1 - (Budget().cost_usd_per_run + compute) / rev), 1),
                "price_for_p95_at_floor": round(runs * p95 / (1 - margin_floor), 2),
            })
        out[name] = row
    return out


def build(trace_json: str, inputs: dict, margin_floor: float = DEFAULT_MARGIN_FLOOR) -> dict:
    traces = run_traces(trace_json)
    d = drivers(traces, float(inputs["vm_price_per_hour"]["value"]))
    costs = [float(t.get("totalCostUsd") or 0) for t in traces]
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "FirstRun run folders (state.json), list price not billed",
        "margin_floor": margin_floor,
        "drivers": d,
        "tiers": tier_caps(d, inputs["tiers"], margin_floor, costs),
    }


def write(econ: dict, out_dir: Path | None = None) -> list[Path]:
    """business/unit_economics.json and business/drivers.csv (the file Ari reads)."""
    out_dir = out_dir or BUSINESS
    out_dir.mkdir(parents=True, exist_ok=True)
    js = out_dir / "unit_economics.json"
    js.write_text(json.dumps(econ, indent=2) + "\n", encoding="utf-8")
    d = econ["drivers"]
    src = f"run folders, {d['traces']} runs"
    rows = [
        ("traces_measured", d["traces"], "traces", "yes", src),
        ("cost_per_run_mean", d["cost_mean"], "USD", "yes", src),
    ]
    for q in ("p50", "p90", "p95", "max"):
        c = d[f"cost_{q}"]
        rows.append((f"cost_per_run_{q}", c["usd"], "USD", "yes", f"run {c['trace_id']}"))
    rows += [
        ("run_duration_mean", d["duration_mean_s"], "seconds", "yes", src),
        ("vm_price_per_hour", d["vm_price_per_hour"], "USD", "no", "AWS t3.medium on-demand, assumption"),
        ("compute_per_run", d["compute_per_run"], "USD", "no", "vm_price_per_hour x run_duration_mean / 3600"),
        ("margin_floor", econ["margin_floor"], "fraction", "no", "assumption, set by the founder"),
    ]
    for name, t in econ["tiers"].items():
        key = name.lower()
        rows.append((f"{key}_price", t["price_usd_month"], "USD per month", "no", "assumption"))
        rows.append((f"{key}_runs_per_month", t["runs_per_month"], "runs", "no", "assumption"))
        rows.append((f"{key}_cost_cap_per_run", t["cap_usd_per_run"], "USD", "no", t["cap_rule"]))
        rows.append((f"{key}_runs_over_cap_pct", t["measured_runs_over_cap_pct"], "percent", "yes", src))
    csv_path = out_dir / "drivers.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["driver", "value", "unit", "measured", "source"])
        w.writerows(rows)
    return [js, csv_path]


def budget_for_tier(tier: str, path: Path | None = None) -> Budget:
    """The run budget with the tier's cost cap from business/unit_economics.json."""
    path = path or BUSINESS / "unit_economics.json"
    if not path.exists():
        raise EconError(f"{path} not found. Run `firstrun econ` first.")
    tiers = json.loads(path.read_text(encoding="utf-8"))["tiers"]
    match = {k.lower(): v for k, v in tiers.items()}.get(tier.lower())
    if match is None:
        raise EconError(f"unknown tier {tier!r}. Known: {', '.join(tiers)}")
    return Budget(cost_usd_per_run=float(match["cap_usd_per_run"]))
