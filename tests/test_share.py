"""Share format v1: round trip, limits, redaction, CLI. Offline."""

from __future__ import annotations

import shutil
from pathlib import Path

from click.testing import CliRunner

from onestrun import cli as cli_mod
from onestrun import share
from onestrun.cli import cli

FIXTURE = Path(__file__).parent / "fixtures_report" / "run-verified"
FAKE_KEY = "sk-ABCDEF0123456789abcdef"


def _copy(tmp_path, name="run-verified") -> Path:
    dest = tmp_path / name
    shutil.copytree(FIXTURE, dest)
    return dest


def test_round_trip():
    payload = {"v": 1, "run_id": "x", "title": "Ünïcode ✓", "steps": []}
    code = share.encode(payload)
    assert "=" not in code and "+" not in code and "/" not in code
    assert share.decode(code) == payload


def test_build_payload_verified_fixture(tmp_path):
    p = share.build_payload(_copy(tmp_path))
    assert p["v"] == 1 and p["status"] == "verified"
    assert p["target"] == "docs.gamma.io" and p["fixture"] is False
    assert [s["id"] for s in p["steps"]] == [1, 2, 3, 4]
    step3 = p["steps"][2]
    assert step3["status"] == "passed" and step3["attempts"] == 2 and step3["exit_code"] == 0
    assert "unrecognized arguments" in step3["error_tail"]
    assert p["verify"] == {"status": "verified", "steps_passed": 4, "steps_total": 4}
    assert p["trace_id"] == ""
    assert share.decode(share.encode(p)) == p


def test_limits(tmp_path):
    run = _copy(tmp_path)
    (run / "patch.diff").write_text("d" * 9000, encoding="utf-8")
    (run / "pr_body.md").write_text("b" * 9000, encoding="utf-8")
    p = share.build_payload(run)
    assert len(p["diff"]) == 4000 and len(p["pr_body"]) == 3000


def test_error_tail_capped_and_redacted(tmp_path):
    import json

    run = _copy(tmp_path)
    state = json.loads((run / "state.json").read_text(encoding="utf-8"))
    for r in state["results"]:
        if not r["passed"]:
            r["stderr"] = "x" * 2000 + f" API_KEY={FAKE_KEY} {FAKE_KEY}"
    state["tags"] = [FAKE_KEY]
    (run / "state.json").write_text(json.dumps(state), encoding="utf-8")
    p = share.build_payload(run)
    assert len(p["steps"][2]["error_tail"]) <= 600
    assert FAKE_KEY not in share.encode(p) and FAKE_KEY not in str(p)


def test_fixture_flag_and_trace_id(tmp_path):
    run = _copy(tmp_path)
    (run / "trace_id").write_text("abc123\n", encoding="utf-8")
    import json

    st = json.loads((run / "state.json").read_text(encoding="utf-8"))
    st["source_url"] = "https://web.archive.org/web/2020/https://x.io/"
    (run / "state.json").write_text(json.dumps(st), encoding="utf-8")
    p = share.build_payload(run)
    assert p["fixture"] is True and p["trace_id"] == "abc123"


def test_share_link_base(monkeypatch):
    monkeypatch.delenv("ONESTRUN_SHARE_BASE", raising=False)
    assert share.share_link("abc") == "https://1strun.rajbir.tech/doc-test/#r=abc"
    monkeypatch.setenv("ONESTRUN_SHARE_BASE", "http://localhost/run.html")
    assert share.share_link("abc") == "http://localhost/run.html#r=abc"


def test_cli_share_by_id_and_default(tmp_runs_dir):
    _copy(tmp_runs_dir, "run-verified")
    for args in (["share", "run-verified"], ["share"]):
        result = CliRunner().invoke(cli, args)
        assert result.exit_code == 0, result.output
        lines = result.output.splitlines()
        assert lines[0].startswith("https://1strun.rajbir.tech/doc-test/#r=")
        code = lines[1].removeprefix("code: ")
        assert share.decode(code)["run_id"] == "run-verified"
        assert lines[2] == f"code length: {len(code)}"


def test_cli_share_unknown_id(tmp_runs_dir):
    result = CliRunner().invoke(cli, ["share", "nope"])
    assert result.exit_code != 0 and "unknown run id" in result.output


def test_run_end_share_line(tmp_runs_dir, capsys):
    _copy(tmp_runs_dir, "run-verified")
    cli_mod._echo_share(tmp_runs_dir / "run-verified")
    assert capsys.readouterr().out.startswith("share: https://1strun.rajbir.tech/doc-test/#r=")


def test_run_end_share_failure_is_silent(tmp_path, capsys):
    cli_mod._echo_share(tmp_path / "missing")
    assert capsys.readouterr().out == ""


def test_steps_carry_docs_quote_and_every_try(tmp_path):
    step3 = share.build_payload(_copy(tmp_path))["steps"][2]
    assert isinstance(step3["quote"], str)
    assert [t["passed"] for t in step3["tries"]] == [False, True]
    assert step3["tries"][0]["exit_code"] != 0 and step3["tries"][1]["exit_code"] == 0


def test_evidence_keeps_known_https_links_only(tmp_path):
    import json

    run = _copy(tmp_path)
    (run / "evidence.json").write_text(json.dumps([
        {"kind": "checkpoint", "label": "Old Entire checkpoint", "url": "https://entire.io/x"},
        {"kind": "comment", "label": "Note", "url": "https://github.com/a/b/issues/1#c1", "public": False},
        {"kind": "pr", "label": "PR", "url": "https://github.com/a/b/pull/1", "step_id": 3},
        {"kind": "trace", "label": "Langfuse trace", "url": "", "public": False},
        {"kind": "pr", "url": "javascript:alert(1)"},
        {"kind": "unknown", "url": "https://x.io"},
    ]), encoding="utf-8")
    ev = share.build_payload(run)["evidence"]
    assert [e["kind"] for e in ev] == ["comment", "pr", "trace"]  # the old checkpoint kind is gone
    assert ev[0]["public"] is False and ev[1]["step_id"] == 3


def test_evidence_absent_or_broken_is_empty(tmp_path):
    run = _copy(tmp_path)
    assert share.build_payload(run)["evidence"] == []
    (run / "evidence.json").write_text("{not json", encoding="utf-8")
    assert share.build_payload(run)["evidence"] == []
