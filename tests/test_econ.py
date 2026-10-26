"""Unit economics from traces and the per-tier budget. Offline."""

from __future__ import annotations

import csv
import json

import pytest
from click.testing import CliRunner

from firstrun import econ
from firstrun.cli import _recover_fn, cli

COSTS = [0.01, 0.02, 0.03, 0.04, 0.10]
TRACES = json.dumps({"data": {"traces": [
    *({"traceName": "firstrun.run", "traceId": f"t{i}", "totalCostUsd": c, "durationMs": 180000}
      for i, c in enumerate(COSTS)),
    {"traceName": "doctor.probe.root", "traceId": "z", "totalCostUsd": 9.0, "durationMs": 1},
]}})
INPUTS = {
    "vm_price_per_hour": {"value": 0.04},
    "tiers": {
        "Free": {"price_usd_month": 0, "runs_per_month": 4},
        "Team": {"price_usd_month": 30, "runs_per_month": 300},
    },
}


def test_drivers_skip_other_traces_and_name_the_quantile_trace():
    d = econ.drivers(econ.run_traces(TRACES), 0.04)
    assert d["traces"] == 5
    assert d["cost_mean"] == 0.04
    assert d["cost_p50"] == {"usd": 0.03, "trace_id": "t2"}
    assert d["cost_max"] == {"usd": 0.10, "trace_id": "t4"}
    assert d["compute_per_run"] == 0.002  # 0.04 x 180 / 3600


def test_cap_keeps_the_margin_floor_when_every_run_hits_it():
    result = econ.build(TRACES, INPUTS, margin_floor=0.70)
    team = result["tiers"]["Team"]
    # $30 / 300 = $0.10 per run. 30% of it is $0.03, minus $0.002 compute.
    assert team["cap_usd_per_run"] == pytest.approx(0.028)
    assert team["measured_runs_over_cap_pct"] == 60.0  # 0.03, 0.04, 0.10
    worst = (team["cap_usd_per_run"] + 0.002) / team["revenue_per_run"]
    assert 1 - worst == pytest.approx(0.70)
    assert team["price_for_p95_at_floor"] == pytest.approx(300 * 0.102 / 0.3)


def test_free_tier_cap_is_the_median_run():
    free = econ.build(TRACES, INPUTS)["tiers"]["Free"]
    assert free["cap_usd_per_run"] == 0.03
    assert "margin_at_mean_pct" not in free


def test_no_traces_is_an_error():
    with pytest.raises(econ.EconError):
        econ.build(json.dumps({"data": {"traces": []}}), INPUTS)


def test_write_and_budget_for_tier(tmp_path):
    econ.write(econ.build(TRACES, INPUTS), tmp_path)
    rows = {r["driver"]: r for r in csv.DictReader((tmp_path / "drivers.csv").open(encoding="utf-8"))}
    assert rows["cost_per_run_max"]["source"] == "run t4"
    assert rows["cost_per_run_mean"]["measured"] == "yes"
    assert rows["team_cost_cap_per_run"]["measured"] == "no"
    budget = econ.budget_for_tier("team", tmp_path / "unit_economics.json")
    assert budget.cost_usd_per_run == pytest.approx(0.028)
    with pytest.raises(econ.EconError):
        econ.budget_for_tier("enterprise", tmp_path / "unit_economics.json")


def test_recover_fn_carries_the_tier_budget():
    budget = econ.Budget(cost_usd_per_run=0.01)
    assert _recover_fn(budget).keywords["budget"] is budget
    assert not hasattr(_recover_fn(), "keywords")


def test_econ_command_offline(tmp_path, monkeypatch):
    (tmp_path / "inputs.json").write_text(json.dumps(INPUTS), encoding="utf-8")
    traces = tmp_path / "traces.json"
    traces.write_text(TRACES, encoding="utf-8")
    monkeypatch.setattr(econ, "BUSINESS", tmp_path)
    res = CliRunner().invoke(cli, ["econ", "--traces", str(traces)])
    assert res.exit_code == 0, res.output
    assert "Team: cap $0.0280 per run, 60.0% of runs over it" in res.output
    assert (tmp_path / "drivers.csv").exists()


def test_run_rejects_unknown_tier(tmp_path, monkeypatch):
    monkeypatch.setattr(econ, "BUSINESS", tmp_path)
    res = CliRunner().invoke(cli, ["run", "https://example.com", "--tier", "team"])
    assert res.exit_code != 0
    assert "Run `firstrun econ` first" in res.output
