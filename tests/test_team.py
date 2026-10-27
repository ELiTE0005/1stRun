"""team map and the ranked list: bots, identities, weights, areas, owners and the board contract. Offline."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from onestrun import audit, intake, nextup, team

ROOT = Path(__file__).resolve().parents[1]
AS_OF = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
NOW = datetime.now(timezone.utc)

_n = iter(range(1, 10**6))


def C(name: str, email: str, files: list[str], days: float = 1, parents: int = 1, subject: str = "fix: x") -> dict:
    """One commit as read_history returns it."""
    when = AS_OF - timedelta(days=days)
    return {"sha": f"{next(_n):040x}", "date": when, "adate": when, "author": name, "email": email, "subject": subject,
            "files": files, "parents": parents, "scope": ""}


def build(commits: list[dict], paths: list[str] | None = None, **kw):
    paths = paths if paths is not None else sorted({f for c in commits for f in c["files"]})
    commits = sorted(commits, key=lambda c: c["adate"], reverse=True)
    return team.build_team([{"repo": "code", "commits": commits, "paths": paths, "slug": ""}], AS_OF, github=False, **kw)


# ----------------------------------------------------------------------------- git helpers

def _git(repo: Path, *args: str, env: dict | None = None) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=env)


def _env(name: str, email: str, days: int) -> dict:
    when = (NOW - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    return {**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when, "GIT_AUTHOR_NAME": name,
            "GIT_AUTHOR_EMAIL": email, "GIT_COMMITTER_NAME": "c", "GIT_COMMITTER_EMAIL": "c@x"}


def _commit(repo: Path, files: dict[str, str], msg: str, days: int, author=("Maya", "12345+maya@users.noreply.github.com")):
    for name, text in files.items():
        p = repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    env = _env(*author, days)
    _git(repo, "add", "-A", env=env)
    _git(repo, "commit", "-q", "-m", msg, env=env)


def _merge(repo: Path, branch: str, msg: str, days: int) -> None:
    _git(repo, "merge", "--no-ff", "-q", "-m", msg, branch, env=_env("Maya", "12345+maya@users.noreply.github.com", days))


@pytest.fixture
def team_repo(tmp_path) -> Path:
    r = tmp_path / "proj"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main", str(r))
    _commit(r, {"README.md": "# Proj\n", "docs/export.md": "# Export\nUse export.\n", "src/export.py": "x=1\n",
                "src/old/gone.py": "x\n"}, "initial", 400, ("Ravi Kumar", "ravi@corp.example"))
    _commit(r, {"src/export.py": "x=2\n"}, "fix(export): handle empty rows (#5)", 60, ("Ravi Kumar", "ravi@corp.example"))
    _git(r, "checkout", "-q", "-b", "side")
    _commit(r, {"src/export.py": "x=3\n"}, "feat: add `--format` flag to export (#7)", 20)
    _git(r, "checkout", "-q", "main")
    _commit(r, {"src/cli.py": "y\n"}, "feat(cli): add a cli entry (#8)", 18, ("Ravi Kumar", "ravi@corp.example"))
    _merge(r, "side", "Merge branch side", 17)
    _git(r, "mv", "src/old/gone.py", "src/kept.py", env=_env("Maya", "m@x", 16))
    _commit(r, {"src/export.py": "x=4\n"}, "feat(export): stream large export files", 15)
    _commit(r, {"package-lock.json": "{}"}, "chore: bump deps", 5, ("dependabot[bot]", "49699333+dependabot[bot]@users.noreply.github.com"))
    _commit(r, {"docs/new.md": "# New\n"}, "docs: new page", 2)
    return r


# ----------------------------------------------------------------------------- (1) history fields

def test_read_history_has_email_author_date_and_parents(team_repo):
    commits = audit.read_history(team_repo)
    merge = next(c for c in commits if c["subject"] == "Merge branch side")
    assert merge["parents"] == 2 and merge["files"] == []
    first = next(c for c in commits if c["subject"] == "initial")
    assert first["parents"] == 0 and first["email"] == "ravi@corp.example"
    assert all(isinstance(c["adate"], datetime) for c in commits)
    assert any(c["email"] == "12345+maya@users.noreply.github.com" for c in commits)


# ----------------------------------------------------------------------------- (2) and (3) identities and bots

def test_noreply_addresses_give_logins():
    assert team.noreply("12345+maya@users.noreply.github.com") == (12345, "maya")
    assert team.noreply("maya@users.noreply.github.com") == (None, "maya")
    assert team.noreply("maya@corp.example") == (None, None)


@pytest.mark.parametrize("name,email", [
    ("dependabot[bot]", "49699333+dependabot[bot]@users.noreply.github.com"),
    ("github-actions[bot]", "41898282+github-actions[bot]@users.noreply.github.com"),
    ("renovate[bot]", "29139614+renovate[bot]@users.noreply.github.com"),
    ("Copilot", "198982749+Copilot@users.noreply.github.com"),
    ("copilot-swe-agent[bot]", "198982749+copilot-swe-agent[bot]@users.noreply.github.com"),
    ("snyk-bot", "snyk-bot@snyk.io"),
    ("FishtownBuildBot", "buildbot@fishtownanalytics.com"),
    ("fa-assistant", "fa@corp.example"),
    ("Claude", "noreply@anthropic.com"),
])
def test_bots_are_skipped(name, email):
    assert team.is_bot(name, email)


@pytest.mark.parametrize("name,email", [("Sam Talbot", "sam.talbot@corp.example"), ("Robert", "robert@corp.example"),
                                        ("Abbot", "abbot@corp.example")])
def test_people_are_not_bots(name, email):
    assert not team.is_bot(name, email)


def test_identities_merge_by_login_email_and_name(monkeypatch):
    commits = [C("Maya Rao", "maya@a.example", ["src/a.py"]), C("maya rao", "maya@b.example", ["src/a.py"]),
               C("Maya Rao", "12345+maya@users.noreply.github.com", ["src/a.py"]),
               C("M R", "maya@c.example", ["src/a.py"]), C("Maya R.", "other@d.example", ["src/a.py"]),
               C("Sam Lee", "1+saml@users.noreply.github.com", ["src/b.py"]),
               C("Sam Lee", "2+samlee@users.noreply.github.com", ["src/b.py"]),
               C("bob@corp.example", "77+bobby@users.noreply.github.com", ["src/c.py"])]
    looked = {}

    def fake(slug, wanted, token=None):
        looked.update(wanted)
        return {"maya@c.example": ("maya", 12345)}

    monkeypatch.setattr(team, "github_logins", fake)
    sources = [{"repo": "code", "commits": commits, "paths": ["src/a.py", "src/b.py", "src/c.py"], "slug": "acme/proj"}]
    t, ctx = team.build_team(sources, AS_OF)
    names = sorted(p["name"] for p in ctx.people.values())
    assert "maya@c.example" in looked
    maya = [p for p in ctx.people.values() if p["login"] == "maya"]
    assert len(maya) == 1 and maya[0]["commits"] == 4  # name, noreply login and GitHub login all join
    assert any(p["name"] == "Maya R." and not p["login"] for p in ctx.people.values())  # no shared key, no merge
    assert sum(1 for p in ctx.people.values() if p["name"] == "Sam Lee") == 2  # two known logins stay two people
    assert "bobby" in names and not any("@" in n for n in names)
    assert t["source"] == "git+github"


# ----------------------------------------------------------------------------- (5) and (6) weights

def test_merges_and_huge_commits_weigh_nothing_and_the_log_cap_holds():
    big = [f"src/big/f{i}.py" for i in range(200)]
    t, ctx = build([C("Ann One", "ann@x.example", ["src/a.py"]), C("Ann One", "ann@x.example", ["src/a.py"], parents=2),
                    C("Bo Two", "bo@x.example", [f"src/huge/f{i}.py" for i in range(301)]),
                    C("Cy Three", "cy@x.example", big)])
    w = {p["name"]: p["weight"] for p in ctx.people.values()}
    assert w["Ann One"] == pytest.approx(team._decay(AS_OF, AS_OF - timedelta(days=1)))  # the merge added nothing
    assert w.get("Bo Two", 0) == 0
    assert w["Cy Three"] <= 4 * w["Ann One"] + 1e-9


def test_a_90_day_old_commit_weighs_half():
    t, ctx = build([C("Ann One", "ann@x.example", ["src/a.py"], days=0), C("Bo Two", "bo@x.example", ["src/a.py"], days=90)])
    w = {p["name"]: p["weight"] for p in ctx.people.values()}
    assert abs(w["Bo Two"] / w["Ann One"] - 0.5) < 1e-6


# ----------------------------------------------------------------------------- (7) and (8) areas

def test_frontier_skips_wrapper_folders_and_maps_deleted_ones():
    commits = []
    for sub in "abc":
        commits += [C("Ann One", "ann@x.example", [f"packages/app/src/{sub}/m{i}.py"]) for i in range(10)]
    commits += [C("Ann One", "ann@x.example", ["README.md"]) for _ in range(3)]
    commits += [C("Ann One", "ann@x.example", ["old/thing/gone.py"]) for _ in range(5)]
    paths = [f"packages/app/src/{s}/m0.py" for s in "abc"] + ["README.md", "old/keep.py"]
    t, _ = build(commits, paths)
    labels = {a["label"]: a for a in t["areas"]}
    assert {"a", "b", "c", "old"} <= set(labels) and "packages" not in labels and "src" not in labels
    assert labels["old"]["path"] == "old/"  # old/thing/ is gone, so its work lands on old/
    assert t["rest"]["share"] > 0  # README.md at the root


def test_area_metrics_shares_bus_single_and_quiet():
    commits = [C("Maya Rao", "m@x.example", ["x/a.py"]) for _ in range(4)] + [C("Ravi Kumar", "r@x.example", ["x/a.py"])]
    commits += [C("Maya Rao", "m@x.example", ["y/a.py"]) for _ in range(2)] + [C("Ravi Kumar", "r@x.example", ["y/a.py"]) for _ in range(2)]
    commits += [C("Lee Park", "l@x.example", ["y/a.py"])]
    commits += [C("Lee Park", "l@x.example", ["z/a.py"], days=200) for _ in range(3)]
    t, _ = build(commits)
    areas = {a["label"]: a for a in t["areas"]}
    assert sum(a["share"] for a in t["areas"]) + t["rest"]["share"] == pytest.approx(1, abs=0.005)
    assert areas["x"]["single"] and areas["x"]["bus"] == 1
    assert not areas["y"]["single"] and areas["y"]["bus"] == 2
    assert areas["z"]["quiet"] and not areas["x"]["quiet"]
    assert areas["x"]["owners"][0]["s"] == 0.8


# ----------------------------------------------------------------------------- (9), (10), (11) people and privacy

def test_one_person_repo_is_one_person_who_holds_every_area(repo_one):
    a = audit.audit(str(repo_one), use_judge=False)
    t = a["team"]
    assert len(t["people"]) == 1 and t["others"] is None
    assert all(ar["single"] and [o["p"] for o in ar["owners"]] == ["p1"] for ar in t["areas"])
    assert all((i["owner"] or {}).get("p", "p1") == "p1" and i["runner_up"] is None for i in a["next"]["items"])


@pytest.fixture
def repo_one(tmp_path) -> Path:
    r = tmp_path / "solo"
    r.mkdir()
    _git(r, "init", "-q", str(r))
    _commit(r, {"README.md": "# Solo\n", "docs/export.md": "# Export\n", "src/export.py": "x=1\n", "lib/util.py": "u\n"},
            "initial", 400)
    for i, d in enumerate((60, 20, 15, 12)):
        _commit(r, {"src/export.py": f"x={i}\n", "lib/util.py": f"u{i}\n"}, f"feat(export): export step {i}", d)
    return r


def test_300_authors_fit_the_budget():
    commits = [C(f"Person {i}", f"p{i}@x.example", [f"m{i % 7}/f{i}.py"]) for i in range(300)]
    commits += [C("Maya Rao", "m@x.example", ["m1/a.py"]) for _ in range(30)]
    t, _ = build(commits)
    assert len(t["people"]) <= 16
    assert t["others"]["people"] == t["total_people"] - len(t["people"]) == 301 - len(t["people"])
    assert len(json.dumps(t)) < 10_000


def test_no_email_reaches_the_board(team_repo):
    a = audit.audit(str(team_repo), use_judge=False)
    text = json.dumps({"team": a["team"], "next": a["next"]}, ensure_ascii=False)
    assert EMAIL.search(text) is None and "noreply" not in text.lower()
    assert all("[bot]" not in p["name"] for p in a["team"]["people"]) and a["team"]["bots_skipped"] == 1


# ----------------------------------------------------------------------------- (12) to (15) the ranked list

def _refresh_board(path: str, evidence: list[dict], status: str = "stale", judge: str = "judge") -> dict:
    page = {"path": path, "title": "Use cases", "status": status, "judge": judge, "relevant_since": len(evidence),
            "age_days": 400, "ancient": False, "last_touched": "2025-09-05", "evidence": evidence}
    return {"cards": [{"kind": "refresh", "title": f"Refresh {path}", "action": "Re-read it.", "evidence": evidence}],
            "pages": [page], "features": [], "release": {"name": "", "commits": 0}}


def _ev(c: dict) -> dict:
    return {"sha": c["sha"][:9], "date": c["date"].date().isoformat(), "subject": c["subject"]}


def test_owner_and_reason_come_from_the_folder_history():
    code = [C("Maya", "m@x.example", ["src/usecases/run.py"], days=3 + i, subject="feat: use case") for i in range(3)]
    docs = []
    for i in range(20):
        who = ("Maya", "m@x.example") if i % 10 < 7 else ("Ravi Kumar", "r@x.example")
        docs.append(C(*who, [f"docs/use-cases/p{i}.md"], days=5 + i))
    t, ctx = build(code + docs, sorted({f for c in code + docs for f in c["files"]} | {"docs/use-cases/x.md"}))
    nxt = nextup.build_next(_refresh_board("docs/use-cases/x.md", [_ev(c) for c in code]), ctx, AS_OF)
    item = nxt["items"][0]
    owner = next(p for p in t["people"] if p["id"] == item["owner"]["p"])
    assert owner["name"] == "Maya"
    assert item["owner"]["why"] == "Maya made 14 of the last 20 commits to docs/use-cases/"
    assert item["runner_up"] and item["runner_up"]["p"] != item["owner"]["p"]


def test_load_balancing_spreads_the_top_10():
    affs = [{"maya": 1.0, "ravi": 0.8, "lee": 0.4}] * 6
    picks = nextup.assign(affs, lambda k: True)
    owners = [p[0] for p in picks]
    assert owners.count("ravi") >= 1 and "lee" not in owners
    assert all(bal for pick, top, _, bal in picks if pick != top) and any(bal for *_, bal in picks)
    assert nextup.assign([{"maya": 1.0}] * 6, lambda k: True)[5][0] == "maya"  # one expert: no cap


def test_no_clear_owner_names_the_last_toucher():
    old = [C("Old Timer", "o@x.example", ["docs/use-cases/x.md"], days=200)]
    code = [C("Old Timer", "o@x.example", ["src/x.py"], days=210, subject="feat: x")]
    t, ctx = build(old + code)
    item = nextup.build_next(_refresh_board("docs/use-cases/x.md", [_ev(code[0])]), ctx, AS_OF)["items"][0]
    day = (AS_OF - timedelta(days=200)).date()
    assert item["owner"] is None
    assert item["fallback"] == f"Last touched by Old Timer on {day:%b} {day.day}, {day.year}"


def _page(i: int, rel: int, ancient: bool = False) -> dict:
    return {"path": f"docs/deep/p{i}.md", "title": f"P{i}", "status": "stale", "judge": "text", "relevant_since": rel,
            "age_days": 800 if ancient else 300, "ancient": ancient, "last_touched": "2025-08-01",
            "evidence": [{"sha": f"{i:09x}", "date": "2026-10-01", "subject": "fix: x"}]}


def _feat(i: int, subject: str, area: str = "", closest: str = "docs/a.md", covered: bool = False) -> dict:
    return {"sha": f"{0xabc000 + i:09x}", "date": "2026-10-05", "subject": subject, "author": "a", "pr": None,
            "term": "x", "area": area, "area_src": "scope" if area else "", "strong": [], "covered": covered,
            "judge": "text", "closest_page": closest, "files": ["src/x.py"]}


def test_scores_caps_dedupe_and_effort():
    pages = [_page(i, rel) for i, rel in enumerate([3, 10, 11, 4, 5, 6, 7, 8])] + [_page(8, 3, ancient=True)]
    feats = [_feat(i, f"feat: thing {i}") for i in range(8)] + [_feat(20, "feat: shiny"), _feat(21, "feat: shiny")]
    ev = lambda f: {"sha": f["sha"], "date": f["date"], "subject": f["subject"], "pr": None}  # noqa: E731
    cards = [{"kind": "document", "title": f"Document: {f['subject']}", "evidence": [ev(f)]} for f in feats[:8]]
    cards += [{"kind": "feature", "title": "Feature this", "evidence": [ev(f)]} for f in (feats[8], feats[9], feats[0])]
    board = {"cards": cards, "pages": pages, "features": feats, "release": {"name": "", "commits": 0}}
    items = nextup.build_next(board, None, AS_OF)["items"]
    for it in items:
        p = it["parts"]
        assert it["score"] == round(100 * sum(nextup.WEIGHTS[k] * p[k] for k in nextup.WEIGHTS))
        assert it["owner"] is None
    top = [i["kind"] for i in items[:10]]
    assert top.count("refresh") <= 5 and top.count("document") <= 5
    announces = [i for i in items if i["kind"] == "announce"]
    assert len(announces) == 1 and announces[0]["title"] == "Announce: Shiny"  # one per subject, none for a documented sha
    effort = {i["path"]: i["effort"] for i in items if i["kind"] == "refresh"}
    assert effort["docs/deep/p0.md"] == "S" and effort["docs/deep/p1.md"] == "M" and effort["docs/deep/p2.md"] == "L"
    assert effort["docs/deep/p8.md"] == "M"  # ancient adds one size
    assert all(i["effort"] == "S" for i in items if i["title"].startswith("Document:"))  # it has a closest page
    assert [i["rank"] for i in items] == list(range(1, len(items) + 1))


def test_cluster_effort_follows_the_page_and_the_count():
    def board(n: int, own: bool) -> dict:
        fs = [_feat(i, f"feat(sync): s{i}", area="sync") for i in range(n)]
        ev = [{"sha": f["sha"], "date": f["date"], "subject": f["subject"], "pr": None} for f in fs[:3]]
        card = {"kind": "document", "count": n, "evidence": ev, "why": f"{n} changes since 2026-10-05.",
                "title": "Document the new `sync` changes" if own else "Document the `sync` feature",
                "action": "Add them to docs/sync.md, the `sync` page, with one example each." if own else "Write it."}
        return {"cards": [card], "pages": [], "features": fs, "release": {"name": "", "commits": 0}}

    def one(n, own):
        return nextup.build_next(board(n, own), None, AS_OF)["items"][0]

    assert one(6, True)["effort"] == "M" and one(7, True)["effort"] == "L"
    assert one(7, False)["effort"] == "M" and one(8, False)["effort"] == "L"
    assert one(6, True)["title"] == "Add the new sync changes to sync.md" and one(7, False)["title"] == "Write a page for sync"


# ----------------------------------------------------------------------------- (16) failure and opt-outs

def test_a_failed_github_lookup_still_finishes_the_audit(team_repo, monkeypatch):
    _git(team_repo, "remote", "add", "origin", "https://github.com/acme/proj.git")
    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise RuntimeError("GitHub is down")

    monkeypatch.setattr(team, "github_logins", boom)
    a = audit.audit(str(team_repo), use_judge=False)
    assert calls and a["team"]["source"] == "git" and a["team"]["people"]


def test_team_math_that_raises_leaves_next_without_owners(team_repo, monkeypatch):
    monkeypatch.setattr(team, "build_team", lambda *a, **k: 1 / 0)
    a = audit.audit(str(team_repo), use_judge=False)
    assert "team" not in a and a["next"]["items"] and all(i["owner"] is None for i in a["next"]["items"])


@pytest.mark.parametrize("how", ["flag", "env", "repo"])
def test_every_opt_out_turns_the_map_off(team_repo, monkeypatch, how):
    if how == "env":
        monkeypatch.setenv("ONESTRUN_TEAM", "0")
    if how == "repo":
        _commit(team_repo, {".github/1stRun.yml": "audit:\n  team: false\n"}, "chore: opt out", 1)
    a = audit.audit(str(team_repo), use_judge=False, team=how != "flag")
    assert a["team"] == {"v": 1, "disabled": how}
    assert a["next"]["items"] and all(i["owner"] is None and i["runner_up"] is None for i in a["next"]["items"])


def test_a_hidden_person_is_never_suggested():
    commits = [C("Maya Rao", "m@x.example", ["src/a.py"]) for _ in range(5)] + [C("Ravi Kumar", "r@x.example", ["src/b.py"])]
    t, ctx = build(commits, hidden={team.optout_hash(team.norm_name("Maya Rao"))})
    assert [p["name"] for p in t["people"]] == ["Ravi Kumar"] and t["others"]["people"] == 1
    assert not any(ctx.active(k) for k, p in ctx.people.items() if p["name"] == "Maya Rao")


def test_audit_submit_strips_people():
    doc = {"team": {"v": 1}, "next": {"items": [{"owner": {"p": "p1", "why": "x"}, "runner_up": None, "fallback": "y"}]}}
    out = team.strip_people(doc)
    assert "team" not in out and out["next"]["items"][0]["owner"] is None and out["next"]["items"][0]["fallback"] is None
    assert doc["team"] == {"v": 1}  # the local copy keeps it


# ----------------------------------------------------------------------------- (17) backfill

def _backfill():
    spec = importlib.util.spec_from_file_location("audit_team_backfill", ROOT / "scripts" / "audit_team_backfill.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_backfill_adds_only_team_and_next(team_repo):
    board = audit.audit(str(team_repo), use_judge=False)
    old = {k: v for k, v in board.items() if k not in ("team", "next")}
    b2 = _backfill().backfill_board(json.loads(json.dumps(old, default=str)), team_repo, github=False)
    assert set(b2) - set(old) == {"team", "next"}
    assert all(b2[k] == json.loads(json.dumps(old[k], default=str)) for k in old)
    assert b2["team"]["people"] and b2["next"]["items"]


# ----------------------------------------------------------------------------- (19) the board contract

BOARDS = sorted((ROOT / "docs" / "audits").glob("audit-*.json"))


@pytest.mark.parametrize("path", BOARDS, ids=[p.stem for p in BOARDS])
def test_published_boards_keep_the_contract(path):
    b = json.loads(path.read_text(encoding="utf-8"))
    intake.validate(json.loads(json.dumps(b)))
    people = {p["id"] for p in (b.get("team") or {}).get("people") or []}
    if b.get("team", {}).get("areas"):
        n_p, n_a = len(b["team"]["people"]), len(b["team"]["areas"])
        assert all(-1 <= c[0] < n_p and 0 <= c[1] < n_a for c in b["team"]["cells"])
        assert len(json.dumps(b["team"], separators=(",", ":"), ensure_ascii=False)) < 10_000
    if "next" in b:
        items = b["next"]["items"]
        assert [i["rank"] for i in items] == list(range(1, len(items) + 1))
        for i in items:
            assert i["effort"] in ("S", "M", "L") and 0 <= i["score"] <= 100
            assert all(re.fullmatch(r"[0-9a-f]{7,12}", e["sha"]) for e in i["evidence"])
            for k in ("owner", "runner_up"):
                assert i.get(k) is None or i[k]["p"] in people
        assert len(json.dumps(b["next"], separators=(",", ":"), ensure_ascii=False)) < 25_000
    text = json.dumps({k: b.get(k) for k in ("team", "next")}, ensure_ascii=False)
    assert EMAIL.search(text) is None


def test_a_dormant_repo_maps_the_year_before_its_last_commit(tmp_path):
    """kleros/kleros had no commit for two years, so a map of the last 12 months held nobody. It maps the code that was built."""
    r = tmp_path / "dormant"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main", str(r))
    _commit(r, {"contracts/Court.sol": "a\n", "test/court.js": "b\n"}, "feat: court", 1200)
    _commit(r, {"contracts/Court.sol": "c\n"}, "fix: court", 700)
    commits = audit.read_history(r)
    t, _ = team.collect({"repo": r, "rev": commits[0]["sha"], "commits": commits}, NOW, github=False, optout={})
    assert t["total_people"] == 1
    assert t["idle_days"] >= 699
    assert t["window_days"] > 365
    assert t["as_of"] == commits[0]["date"].date().isoformat()
    assert any(a["label"].startswith("contracts") or a["path"].startswith("contracts") for a in t["areas"])
    live = tmp_path / "live"
    live.mkdir()
    _git(live, "init", "-q", "-b", "main", str(live))
    _commit(live, {"src/a.py": "a\n"}, "feat: a", 10)
    lc = audit.read_history(live)
    t2, _ = team.collect({"repo": live, "rev": lc[0]["sha"], "commits": lc}, NOW, github=False, optout={})
    assert "idle_days" not in t2
