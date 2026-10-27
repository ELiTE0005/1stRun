import json
import re
from urllib.parse import parse_qs, urlparse

import pytest

from onestrun import intake


def test_repo_name_accepts_names_and_links():
    assert intake.repo_name("fastapi/typer") == "fastapi/typer"
    assert intake.repo_name("https://github.com/dbt-labs/dbt-core.git") == "dbt-labs/dbt-core"
    assert intake.repo_name("https://github.com/o/r/") == "o/r"
    assert intake.repo_name("not a repo") == ""
    assert intake.repo_name("../etc") == ""


def test_request_url_prefills_the_issue_form():
    q = parse_qs(urlparse(intake.request_url("fastapi/typer")).query)
    assert q["template"] == ["audit-request.yml"]
    assert q["repo"] == ["fastapi/typer"]
    assert q["title"] == ["Audit request: fastapi/typer"]


def test_parse_issue_reads_the_form_body():
    body = ("### GitHub repo\n\nhttps://github.com/fastapi/typer\n\n"
            "### Audit gist (private repos only)\n\n_No response_\n")
    assert intake.parse_issue(body) == {"repo": "fastapi/typer", "gist": "", "team": True}
    body2 = ("### GitHub repo\n\nacme/private\n\n### Audit gist (private repos only)\n\n"
             "https://gist.github.com/someone/0123456789abcdef0123\n")
    assert intake.parse_issue(body2) == {"repo": "acme/private", "gist": "0123456789abcdef0123", "team": True}
    assert intake.parse_issue("$(rm -rf /)") == {"repo": "", "gist": "", "team": True}


def test_parse_issue_reads_the_team_checkbox():
    base = "### GitHub repo\n\nfastapi/typer\n\n### Team map\n\n"
    assert intake.parse_issue(base + "- [X] Leave out the team map (contributor names and avatars)\n")["team"] is False
    assert intake.parse_issue(base + "- [ ] Leave out the team map (contributor names and avatars)\n")["team"] is True


def test_validate_keeps_an_old_board_as_it_was():
    doc = intake.validate(_audit())
    assert "team" not in doc and "next" not in doc


def test_validate_sanitizes_a_malicious_team_map():
    d = _audit()
    people = [{"id": f"p{i + 1}", "name": f"Eve {i} eve{i}@corp.com", "login": "bad login" if i % 2 else f"eve{i}",
               "gh": "123" if i % 3 else 7, "ini": "EV", "commits": 1, "share": 0.0, "last": "2026-10-01", "top": None,
               "top_share": 0, "email": f"eve{i}@corp.com"} for i in range(500)]
    d["team"] = {"v": 1, "people": people, "areas": [], "cells": [[0, 5, 1.0], [999, 0, 1.0]], "secret": "x@y.io"}
    d["next"] = {"v": 1, "items": [{"rank": 1, "title": "Ask maya@corp.com", "owner": {"p": "p9999", "why": "x"},
                                    "evidence": [{"sha": "not-a-sha"}, {"sha": "c78b284e6"}]}]}
    doc = intake.validate(d)
    text = json.dumps({"team": doc["team"], "next": doc["next"]})
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
    assert len(doc["team"]["people"]) <= 16 and "secret" not in doc["team"]
    assert all("email" not in p for p in doc["team"]["people"])
    assert all(p["login"] is None or re.fullmatch(r"[A-Za-z0-9-]{1,39}", p["login"]) for p in doc["team"]["people"])
    assert all(p["gh"] is None or type(p["gh"]) is int for p in doc["team"]["people"])
    assert doc["team"]["cells"] == []
    item = doc["next"]["items"][0]
    assert item["owner"] is None and [e["sha"] for e in item["evidence"]] == ["c78b284e6"]


def _audit():
    return {"id": "audit-20261011-010203-acme-private", "repo": "acme/private", "generated_at": "2026-10-11T01:02:03+00:00",
            "url": "javascript:alert(1)", "release": {"name": "v1"}, "pages": [], "cards": [],
            "summary": {k: 0 for k in ("pages", "stale", "quiet", "oldest_days", "median_age_days", "features",
                                       "uncovered", "cards")}}


def test_validate_keeps_a_good_audit_and_drops_unsafe_links():
    doc = intake.validate(_audit())
    assert doc["url"] == "" and doc["source"] == "submitted"


@pytest.mark.parametrize("breaks", [
    lambda d: d.pop("summary"),
    lambda d: d.update(id="../../etc/passwd"),
    lambda d: d["summary"].pop("stale"),
    lambda d: d.update(pages="x"),
])
def test_validate_refuses_a_broken_audit(breaks):
    d = _audit()
    breaks(d)
    with pytest.raises(ValueError):
        intake.validate(d)
