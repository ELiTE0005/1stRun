"""Run cache. Offline, tmp runs dir."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from click.testing import CliRunner

from onestrun import cache, executor, planner
from onestrun.cli import cli

URL = "https://Docs.Example.com/quickstart/?x=1#top"


def _write(root, run_id, status="verified", url=URL, age_h=1.0):
    d = root / run_id
    d.mkdir()
    done = (datetime.now(timezone.utc) - timedelta(hours=age_h)).isoformat()
    (d / "state.json").write_text(json.dumps({
        "run_id": run_id, "source_url": url, "status": status, "finished_at": done,
        "step_status": {"1": "passed", "2": "passed"}}), encoding="utf-8")
    (d / "runbook.json").write_text(json.dumps({"source_url": url, "steps": [{}, {}]}), encoding="utf-8")


def test_hit_returns_newest_verified(tmp_runs_dir):
    _write(tmp_runs_dir, "old", age_h=5)
    _write(tmp_runs_dir, "new", status="passed", age_h=1)
    assert cache.find_recent("https://docs.example.com/quickstart") == "new"


def test_failed_and_old_ignored(tmp_runs_dir):
    _write(tmp_runs_dir, "bad", status="failed", age_h=1)
    _write(tmp_runs_dir, "run", status="running", age_h=1)
    _write(tmp_runs_dir, "stale", age_h=30)
    assert cache.find_recent(URL) is None


def test_env_override_and_disable(tmp_runs_dir, monkeypatch):
    _write(tmp_runs_dir, "a", age_h=5)
    monkeypatch.setenv("ONESTRUN_CACHE_HOURS", "2")
    assert cache.find_recent(URL) is None
    monkeypatch.setenv("ONESTRUN_CACHE_HOURS", "48")
    assert cache.find_recent(URL) == "a"
    monkeypatch.setenv("ONESTRUN_CACHE_HOURS", "0")
    assert cache.find_recent(URL) is None


def _boom(*a, **k):
    raise AssertionError("must not run")


def test_cli_cached_path_makes_no_calls(tmp_runs_dir, monkeypatch):
    _write(tmp_runs_dir, "hit")
    monkeypatch.setattr(planner, "plan", _boom)
    monkeypatch.setattr(executor, "run", _boom)
    result = CliRunner().invoke(cli, ["https://docs.example.com/quickstart", "--offline"])
    assert result.exit_code == 0, result.output
    assert "cached: tested" in result.output
    assert "2/2 steps (use --fresh to run again)" in result.output
    assert "report:" in result.output


def test_fresh_bypasses(tmp_runs_dir, monkeypatch):
    from onestrun import cli as cli_mod
    from onestrun.models import RunState, RunStatus

    _write(tmp_runs_dir, "hit")
    seen = []
    monkeypatch.setattr(cli_mod, "_run_one", lambda url, *a, **k: seen.append(url) or RunState(
        run_id="r", source_url=url, status=RunStatus.PASSED))
    result = CliRunner().invoke(cli, [URL, "--offline", "--fresh"])
    assert result.exit_code == 0, result.output
    assert seen == [URL]
