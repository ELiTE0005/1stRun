"""CLI routing and friendly setup errors. Offline."""

from __future__ import annotations

from click.testing import CliRunner

from onestrun import cli as cli_mod
from onestrun.cli import cli, friendly
from onestrun.models import RunState, RunStatus


def _stub_run(monkeypatch):
    seen = {}

    def fake(url, tags, resume, verify, recover=True, budget=None):
        seen["url"] = url
        return RunState(run_id="r", source_url=url, status=RunStatus.PASSED)

    monkeypatch.setattr(cli_mod, "_run_one", fake)
    return seen


def test_bare_url_routes_to_run(monkeypatch, tmp_runs_dir):
    seen = _stub_run(monkeypatch)
    result = CliRunner().invoke(cli, ["https://example.com/docs", "--offline", "--no-verify"])
    assert result.exit_code == 0, result.output
    assert seen["url"] == "https://example.com/docs"


def test_bare_path_routes_to_run(monkeypatch, tmp_runs_dir):
    seen = _stub_run(monkeypatch)
    result = CliRunner().invoke(cli, ["./README.md", "--offline"])
    assert result.exit_code == 0, result.output
    assert seen["url"] == "./README.md"


def test_report_still_a_command(tmp_runs_dir):
    result = CliRunner().invoke(cli, ["report"])
    assert result.exit_code == 0


def test_missing_token_is_one_sentence_exit_2(monkeypatch, tmp_runs_dir):
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setattr(cli_mod.config, "load_env", lambda *a, **k: None)
    result = CliRunner().invoke(cli, ["https://example.com/docs"])
    assert result.exit_code == 2
    assert "CLAUDE_CODE_OAUTH_TOKEN" in result.output and "claude setup-token" in result.output


def test_docker_exception_maps_to_exit_2(monkeypatch, tmp_runs_dir):
    from onestrun.sandbox import DockerUnavailable

    def boom(*a, **k):
        raise DockerUnavailable("docker unavailable: nope")

    monkeypatch.setattr(cli_mod, "_run_one", boom)
    result = CliRunner().invoke(cli, ["https://example.com/docs", "--offline"])
    assert result.exit_code == 2
    assert "wsl -d Ubuntu-22.04 sudo service docker start" in result.output


def test_friendly_mapping():
    assert "Docker is not running" in friendly("docker unavailable: x")
    assert "CLAUDE_CODE_OAUTH_TOKEN" in friendly("model auth failed: 401")
    assert friendly("out of scope") == "out of scope"
