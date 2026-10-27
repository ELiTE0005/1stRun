import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from onestrun import config, docs_source, pr
from onestrun.cli import cli

FIX = Path(__file__).parent / "fixtures_report"
DIFF = "--- a/local.md\n+++ b/local.md\n@@ -1,2 +1,2 @@\n-pip install x==0.3\n+pip install x\n y\n"
BODY = "Fix a broken command in the quickstart\n\nBody text.\n"


def _run(tmp_path, name="run-verified", source=None, diff=True):
    d = tmp_path / name
    shutil.copytree(FIX / name, d)
    if source:
        s = json.loads((d / "state.json").read_text(encoding="utf-8"))
        s["source_url"] = source
        (d / "state.json").write_text(json.dumps(s), encoding="utf-8")
    if diff:
        (d / "patch.diff").write_text(DIFF, encoding="utf-8")
        (d / "pr_body.md").write_text(BODY, encoding="utf-8")
    return d


def test_edit_link_parsing():
    md = "text [Edit this page](https://github.com/acme/docs/edit/dev/docs/start/quick.md) more"
    assert docs_source.find("https://x.io/a", md) == {
        "repo": "acme/docs", "path": "docs/start/quick.md", "branch": "dev", "how": "edit-link"}
    blob = docs_source.find("https://x.io/a", "https://github.com/o/r/blob/main/README.md")
    assert blob["repo"] == "o/r" and blob["path"] == "README.md"


def test_known_site_and_unknown():
    got = docs_source.find("https://docs.getdbt.com/guides/duckdb?step=1", "")
    assert got["repo"] == "dbt-labs/docs.getdbt.com" and got["how"] == "known-site"
    assert docs_source.find("https://www.mkdocs.org/getting-started/", "")["path"] == "docs/getting-started.md"
    assert docs_source.find("https://docs.dagster.io/getting-started/quickstart", "")["repo"] == "dagster-io/dagster"
    assert docs_source.find("https://nowhere.example/x", "")["how"] == "unknown"
    typer = docs_source.find("https://typer.tiangolo.com/tutorial/first-steps/", "")
    assert (typer["repo"], typer["branch"]) == ("fastapi/typer", "master")


def test_unverified_run_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path)
    d = _run(tmp_path, "run-failed")
    with pytest.raises(pr.NotReady):
        pr.plan(d)
    res = CliRunner().invoke(cli, ["pr", "run-failed"])
    assert "not verified" in res.output
    assert res.exit_code == 1


def test_plan_known_site(tmp_path):
    d = _run(tmp_path, source="https://docs.getdbt.com/guides/duckdb")
    text = pr.plan(d)
    assert text.startswith("Review the diff below. Run these only after the human says yes.")
    assert "gh repo fork dbt-labs/docs.getdbt.com --clone" in text
    assert "gh pr create --repo dbt-labs/docs.getdbt.com" in text
    assert "--body-file" in text and "pr_body.md" in text
    assert "+++ b/website/docs/guides/duckdb-qs.md" in text
    assert (d / "patch.repo.diff").read_text(encoding="utf-8").startswith("--- a/website/docs/guides/duckdb-qs.md")


def test_plan_unknown_uses_placeholders(tmp_path):
    d = _run(tmp_path, source="https://nowhere.example/x")
    text = pr.plan(d)
    assert "OWNER/REPO" in text and "PATH" in text and "Edit this page" in text


def test_json_mode(tmp_path, monkeypatch):
    d = _run(tmp_path, source="https://www.mkdocs.org/getting-started/")
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path)
    res = CliRunner().invoke(cli, ["pr", d.name, "--json"])
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert set(data) == {"repo", "path", "branch", "diff", "pr_body", "commands"}
    assert data["repo"] == "mkdocs/mkdocs" and data["path"] == "docs/getting-started.md"
    assert any(c.startswith("gh pr create") for c in data["commands"])


def test_json_error_is_the_documented_object(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path)
    res = CliRunner().invoke(cli, ["pr", "--json"])
    assert res.exit_code == 1
    out = json.loads(res.output)
    assert out["ok"] is False and out["command"] == "pr" and out["error"]["code"] == "not_found"
    plain = CliRunner().invoke(cli, ["pr"])
    assert plain.exit_code == 1 and plain.output.startswith("✗ ")
