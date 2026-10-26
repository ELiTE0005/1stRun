"""--json output and `firstrun doctor`, the parts an agent reads instead of prose. Offline."""

from __future__ import annotations

import json

from click.testing import CliRunner

from firstrun import cli as cli_mod, doctor, state as state_io
from firstrun.cli import cli, error_code
from firstrun.models import Runbook, RunState, RunStatus, Step, StepResult, StepStatus


def _one_json(result) -> dict:
    """stdout must hold exactly one JSON object and nothing else."""
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1, result.stdout
    return json.loads(lines[0])


def _fake_run(monkeypatch, status=RunStatus.VERIFIED, fail_step=None):
    """Replace _run_one with a stub that writes a real run folder."""

    def fake(url, tags, resume, verify, recover=True, budget=None):
        print(f"target: {url}")  # a human line. It must land on stderr in --json mode
        rid = "20990101-000000-docs-example-com"
        steps = [Step(id=1, intent="install", command="pip install x"), Step(id=2, intent="run", command="x go")]
        st = RunState(run_id=rid, source_url=url, status=status, started_at="2099-01-01T00:00:00+00:00",
                      finished_at="2099-01-01T00:01:40+00:00", time_to_first_success_s=100.0)
        st.step_status = {1: StepStatus.PASSED, 2: StepStatus.FAILED if fail_step else StepStatus.PASSED}
        if fail_step:
            st.first_failed_step = fail_step
            st.results = [StepResult(step_id=2, command="x go", exit_code=127, stderr="x: command not found")]
        st.usage.cost_usd = 0.0123
        state_io.save_runbook(rid, Runbook(source_url=url, steps=steps))
        state_io.save_state(st)
        (state_io.run_dir(rid) / "report.md").write_text("# report\n", encoding="utf-8")
        return st

    monkeypatch.setattr(cli_mod, "_run_one", fake)
    monkeypatch.setattr(cli_mod.config, "load_env", lambda *a, **k: None)


def test_run_json_is_one_object_and_logs_go_to_stderr(monkeypatch, tmp_runs_dir):
    _fake_run(monkeypatch)
    res = CliRunner().invoke(cli, ["run", "https://docs.example.com/qs", "--offline", "--fresh", "--json"])
    assert res.exit_code == 0, res.output
    out = _one_json(res)
    assert out["ok"] is True and out["command"] == "run" and out["exit_code"] == 0 and out["error"] is None
    r = out["runs"][0]
    assert r["status"] == "verified" and r["verified"] is True and r["steps_total"] == 2 and r["steps_passed"] == 2
    assert r["cost_usd"] == 0.0123 and r["elapsed_s"] == 100.0 and r["cached"] is False
    assert r["files"]["report.md"].endswith("report.md") and r["files"]["patch.diff"] is None
    assert "target: https://docs.example.com/qs" in res.stderr


def test_run_json_failed_step_lifts_the_error(monkeypatch, tmp_runs_dir):
    _fake_run(monkeypatch, status=RunStatus.FAILED, fail_step=2)
    res = CliRunner().invoke(cli, ["run", "https://docs.example.com/qs", "--offline", "--fresh", "--json"])
    assert res.exit_code == 1
    out = _one_json(res)
    assert out["ok"] is False and out["exit_code"] == 1
    assert out["error"]["code"] == "step_failed" and "command not found" in out["error"]["message"]
    assert out["runs"][0]["reported_failed_step"] == 2


def test_run_json_cached_hit(monkeypatch, tmp_runs_dir):
    _fake_run(monkeypatch)
    CliRunner().invoke(cli, ["run", "https://docs.example.com/qs", "--offline", "--fresh"])
    from firstrun import cache

    monkeypatch.setattr(cache, "find_recent", lambda u, *a, **k: "20990101-000000-docs-example-com")
    res = CliRunner().invoke(cli, ["run", "https://docs.example.com/qs", "--json"])
    assert res.exit_code == 0, res.output
    assert _one_json(res)["runs"][0]["cached"] is True


def test_run_json_missing_token(monkeypatch, tmp_runs_dir):
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setattr(cli_mod.config, "load_env", lambda *a, **k: None)
    res = CliRunner().invoke(cli, ["run", "https://docs.example.com/qs", "--fresh", "--json"])
    assert res.exit_code == 2
    out = _one_json(res)
    assert out["error"]["code"] == "auth_missing" and out["runs"] == []
    assert "claude setup-token" in out["error"]["message"]


def test_run_json_docker_missing(monkeypatch, tmp_runs_dir):
    from firstrun.sandbox import DockerUnavailable

    def boom(*a, **k):
        raise DockerUnavailable("docker unavailable: nope")

    monkeypatch.setattr(cli_mod, "_run_one", boom)
    res = CliRunner().invoke(cli, ["run", "https://docs.example.com/qs", "--offline", "--fresh", "--json"])
    assert res.exit_code == 2
    assert _one_json(res)["error"]["code"] == "docker_unavailable"


def test_run_without_json_prints_no_json(monkeypatch, tmp_runs_dir):
    _fake_run(monkeypatch)
    res = CliRunner().invoke(cli, ["run", "https://docs.example.com/qs", "--offline", "--fresh"])
    assert res.exit_code == 0
    assert not res.stdout.lstrip().startswith("{") and "target:" in res.stdout


AUDIT = {
    "id": "audit-20990101-000000-o-r", "repo": "o/r", "url": "https://github.com/o/r", "docs_repo": "", "mode": "repo",
    "summary": {"pages": 3, "fresh": 1, "aging": 0, "stale": 1, "quiet": 1, "unchecked": 0, "oldest_days": 400,
                "median_age_days": 90, "features": 2, "uncovered": 1, "cards": 2},
    "jev": False, "cost": {"jev_calls": 0, "jev_input_tokens": 0, "jev_usd": 0.0},
    "team": {"people": [{"id": "p1", "name": "Ada L", "login": "ada"}]},
    "next": {"items": [{"rank": i, "kind": "refresh", "title": f"Task {i}", "path": f"docs/{i}.md", "score": 90 - i,
                        "effort": "S", "action": "Edit it.", "rationale": "Code moved.",
                        "owner": {"p": "p1", "why": "Ada made 3 of 4 commits"} if i == 1 else None}
                       for i in range(1, 13)]},
}


def _fake_audit(monkeypatch, tmp_path, fail: str = ""):
    from firstrun import audit as audit_mod

    def fake(target, *a, **k):
        print("cloning")  # must go to stderr in --json mode
        if fail:
            raise RuntimeError(fail)
        return json.loads(json.dumps(AUDIT))

    def save(a, out_dir):
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "audit.json").write_text(json.dumps(a), encoding="utf-8")
        (out_dir / "audit.md").write_text("# audit\n", encoding="utf-8")
        return out_dir / "audit.md"

    monkeypatch.setattr(audit_mod, "audit", fake)
    monkeypatch.setattr(audit_mod, "save", save)


def test_audit_json_top_tasks_and_owner(monkeypatch, tmp_runs_dir):
    _fake_audit(monkeypatch, tmp_runs_dir)
    res = CliRunner().invoke(cli, ["audit", "o/r", "--no-publish", "--json"])
    assert res.exit_code == 0, res.output
    out = _one_json(res)
    assert out["ok"] and out["audit_id"] == AUDIT["id"] and out["summary"]["stale"] == 1
    assert len(out["top_tasks"]) == 10 and out["top_tasks"][0]["rank"] == 1
    assert out["top_tasks"][0]["owner"] == {"name": "Ada L", "login": "ada", "why": "Ada made 3 of 4 commits"}
    assert out["top_tasks"][1]["owner"] is None
    assert out["files"]["audit_json"].endswith("audit.json") and out["published"] is None and out["team"] is True
    assert "cloning" in res.stderr


def test_audit_json_clone_failure(monkeypatch, tmp_runs_dir):
    _fake_audit(monkeypatch, tmp_runs_dir, fail="clone failed: repository not found")
    res = CliRunner().invoke(cli, ["audit", "o/nope", "--no-publish", "--json"])
    assert res.exit_code == 1
    out = _one_json(res)
    assert out["ok"] is False and out["error"]["code"] == "clone_failed"


def _receipt_file(tmp_path, edit: bool = False):
    from firstrun import receipt

    r = {"kind": "audit", "receipt_id": "FR-x", "price": {"usd": 0.0001}, "proof": {"cards": 1},
         "audit": {"audit_id": "x", "evidence_sha256": {}}}
    r["hash"] = receipt.body_hash(r)
    if edit:
        r["price"]["usd"] = 0
    p = tmp_path / "receipt.json"
    p.write_text(json.dumps(r), encoding="utf-8")
    return p


def test_receipt_check_json_ok(tmp_runs_dir):
    res = CliRunner().invoke(cli, ["receipt", "--check", str(_receipt_file(tmp_runs_dir)), "--json"])
    assert res.exit_code == 0, res.output
    out = _one_json(res)
    assert out["mode"] == "check" and out["valid"] is True and out["hash_ok"] is True and out["problems"] == []


def test_receipt_check_json_edited(tmp_runs_dir):
    res = CliRunner().invoke(cli, ["receipt", "--check", str(_receipt_file(tmp_runs_dir, edit=True)), "--json"])
    assert res.exit_code == 1
    out = _one_json(res)
    assert out["valid"] is False and out["hash_ok"] is False and out["error"]["code"] == "receipt_invalid"


def test_receipt_check_hash_only_for_a_site_receipt(tmp_runs_dir):
    from firstrun import receipt

    r = {"receipt_id": "FR-x", "price": {"model_cost_usd": 0.01}, "proof": {"verified": True},
         "audit": {"run_id": "gone", "evidence_sha256": {"state.json": "sha256:00"}}}
    r["hash"] = receipt.body_hash(r)
    p = tmp_runs_dir / "site" / "FR-x.json"
    p.parent.mkdir()
    p.write_text(json.dumps(r), encoding="utf-8")
    full = CliRunner().invoke(cli, ["receipt", "--check", str(p), "--json"])
    assert full.exit_code == 1 and _one_json(full)["hash_ok"] is True
    res = CliRunner().invoke(cli, ["receipt", "--check", str(p), "--hash-only", "--json"])
    assert res.exit_code == 0, res.output
    out = _one_json(res)
    assert out["valid"] is True and out["hash_only"] is True and out["problems"] == []


def test_receipt_unknown_run_json(tmp_runs_dir):
    res = CliRunner().invoke(cli, ["receipt", "nope", "--json"])
    assert res.exit_code == 1
    assert _one_json(res)["error"]["code"] == "unknown_run_id"


def _doctor_env(monkeypatch, docker_ok=True, token=True, net_ok=True):
    monkeypatch.setattr(doctor.config, "load_env", lambda *a, **k: None)
    monkeypatch.setattr(doctor, "probe_docker", lambda: (docker_ok, "docker info"))
    monkeypatch.setattr(doctor, "probe_url", lambda url: (net_ok, url))
    monkeypatch.setattr("firstrun.team._token", lambda: "")
    for k in ("TYPESAFE_API_KEY", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "GITHUB_TOKEN", "GH_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    if token:
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "test-value-not-a-real-token")
    else:
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)


def test_doctor_json_ready_and_never_prints_a_value(monkeypatch):
    _doctor_env(monkeypatch)
    res = CliRunner().invoke(cli, ["doctor", "--json"])
    assert res.exit_code == 0, res.output
    out = _one_json(res)
    assert out["can_run"] == {"doc_test": True, "doc_audit": True, "hosted_audit": True, "read_public_data": True}
    checks = {c["name"]: c for c in out["checks"]}
    assert checks["TYPESAFE_API_KEY"]["status"] == "warn" and checks["CLAUDE_CODE_OAUTH_TOKEN"]["status"] == "pass"
    assert "test-value-not-a-real-token" not in res.stdout + res.stderr


def test_doctor_exit_codes_follow_the_tool(monkeypatch):
    _doctor_env(monkeypatch, docker_ok=False, token=False)
    res = CliRunner().invoke(cli, ["doctor", "--json"])
    assert res.exit_code == 1
    out = _one_json(res)
    assert out["error"]["code"] == "not_ready" and "docker" in out["error"]["message"]
    assert out["can_run"]["doc_test"] is False and out["can_run"]["doc_audit"] is True
    fixes = {c["name"]: c["fix"] for c in out["checks"]}
    assert "claude setup-token" in fixes["CLAUDE_CODE_OAUTH_TOKEN"]
    assert CliRunner().invoke(cli, ["doctor", "--for", "audit", "--json"]).exit_code == 0
    assert CliRunner().invoke(cli, ["doctor", "--for", "test"]).exit_code == 1


def test_doctor_no_network_blocks_audit(monkeypatch):
    _doctor_env(monkeypatch, net_ok=False)
    res = CliRunner().invoke(cli, ["doctor", "--for", "audit", "--json"])
    assert res.exit_code == 1 and _one_json(res)["can_run"]["doc_audit"] is False


def test_probe_url_retries_one_timeout(monkeypatch):
    import httpx

    calls = []

    class R:
        status_code = 200

    def get(url, **k):
        calls.append(url)
        if len(calls) == 1:
            raise httpx.ReadTimeout("slow")
        return R()

    monkeypatch.setattr(httpx, "get", get)
    assert doctor.probe_url("https://github.com") == (True, "https://github.com: HTTP 200") and len(calls) == 2
    calls.clear()
    monkeypatch.setattr(httpx, "get", lambda url, **k: (_ for _ in ()).throw(httpx.ConnectError("down")))
    ok, detail = doctor.probe_url("https://github.com")
    assert not ok and "after 2 tries" in detail


def test_prereqs_json_no_prove(monkeypatch, tmp_runs_dir):
    from firstrun import prereqs

    rid = "20990101-000000-docs-example-com"
    state_io.save_runbook(rid, Runbook(source_url="https://docs.example.com", steps=[Step(id=1, intent="i", command="c")]))
    state_io.save_state(RunState(run_id=rid, source_url="https://docs.example.com", status=RunStatus.VERIFIED))
    monkeypatch.setattr(prereqs, "derive", lambda st, rb: {"system_packages": ["curl"], "python": "", "path": [],
                                                            "secrets": []})
    monkeypatch.setattr(cli_mod.config, "load_env", lambda *a, **k: None)
    res = CliRunner().invoke(cli, ["prereqs", rid, "--no-prove", "--json"])
    assert res.exit_code == 0, res.output
    out = _one_json(res)
    assert out["run_id"] == rid and out["prereqs"]["system_packages"] == ["curl"] and out["proof"] is None


def test_error_codes():
    assert error_code("docs unreachable: HTTP 404 for x") == "docs_unreachable"
    assert error_code(cli_mod.DOCKER_FIX) == "docker_unavailable"
    assert error_code(cli_mod.AUTH_FIX) == "auth_missing"
    assert error_code("cost budget spent: $0.6 of $0.5") == "budget_spent"
    assert error_code("no runnable steps") == "no_runnable_steps"
    assert error_code("something new") == ""
