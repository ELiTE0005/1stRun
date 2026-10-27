"""audit: stale against quiet pages, features with no docs, cards and drafts, on a local git repo."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from onestrun import audit

NOW = datetime.now(timezone.utc)


def _commit(repo: Path, files: dict[str, str], msg: str, days_ago: int, author: tuple[str, str] = ("a", "a@x")) -> None:
    for name, text in files.items():
        p = repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    when = (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    env = {**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when,
           "GIT_AUTHOR_NAME": author[0], "GIT_AUTHOR_EMAIL": author[1], "GIT_COMMITTER_NAME": "a", "GIT_COMMITTER_EMAIL": "a@x"}
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", msg], check=True, env=env)


def _tag(repo: Path, name: str, days_ago: int) -> None:
    when = (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    env = {**os.environ, "GIT_COMMITTER_DATE": when, "GIT_COMMITTER_NAME": "a", "GIT_COMMITTER_EMAIL": "a@x"}
    subprocess.run(["git", "-C", str(repo), "tag", "-a", name, "-m", name], check=True, env=env)


@pytest.fixture
def repo(tmp_path) -> Path:
    r = tmp_path / "proj"
    r.mkdir()
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    _commit(r, {"README.md": "# Proj\n", "docs/export.md": "# Export\nUse export.\n",
                "docs/about.md": "# About\nWe are a team.\n", "src/export.py": "x=1\n"}, "initial", 400)
    _tag(r, "v1.0", 399)
    _commit(r, {"src/export.py": "x=2\n"}, "fix(export): handle empty rows (#5)", 60)
    _commit(r, {"src/export.py": "x=3\n"}, "feat: add `--format` flag to export (#7)", 20)
    _commit(r, {"src/export.py": "x=4\n"}, "feat(export): stream large export files", 15)
    _commit(r, {"src/export.py": "x=5\n"}, "export: speed up export writer", 12)
    _commit(r, {"package-lock.json": "{}"}, "chore: bump deps", 5)
    _commit(r, {"docs/new.md": "# New\nFresh page.\n"}, "docs: new page", 2)
    _tag(r, "v1.1", 1)
    return r


def test_classify_subject_reads_conventional_commits_and_gitmoji():
    assert audit.classify_subject("feat(api): add stream (#3)") == "feature"
    assert audit.classify_subject("fix: crash on empty") == "fix"
    assert audit.classify_subject("chore: bump deps") == "internal"
    assert audit.classify_subject("✨ Add a thing (#9)") == "feature"
    assert audit.classify_subject("🐛 Fix a thing") == "fix"
    assert audit.classify_subject("⬆ Bump urllib3") == "internal"
    assert audit.classify_subject("Something vague") == "unknown"


def test_is_doc_path():
    assert audit.is_doc_path("docs/guide/intro.md")
    assert audit.is_doc_path("README.md")
    assert not audit.is_doc_path("CHANGELOG.md")
    assert not audit.is_doc_path("docs/zh/intro.md")
    assert not audit.is_doc_path("src/readme.py")
    assert not audit.is_doc_path("node_modules/x/docs/a.md")


def test_a_docs_site_repo_counts_every_page_in_its_topic_folders(tmp_path):
    """kleros/docs is a Mintlify site: court/, concepts/ and the rest sit at the root, beside docs.json."""
    r = tmp_path / "site"
    r.mkdir()
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    _commit(r, {"README.md": "# Site\n", "docs.json": "{}", "court/jurors.mdx": "# Jurors\n", "concepts/disputes.mdx": "# Disputes\n",
                "contributing/how.md": "# How\n", "mava.js": "x=1\n"}, "initial", 30)
    assert sorted(audit.head_docs(r)) == ["README.md", "concepts/disputes.mdx", "court/jurors.mdx"]
    plain = tmp_path / "plain"
    plain.mkdir()
    subprocess.run(["git", "init", "-q", str(plain)], check=True)
    _commit(plain, {"README.md": "# P\n", "court/jurors.mdx": "# Jurors\n"}, "initial", 30)
    assert audit.head_docs(plain) == ["README.md"]


def test_resolve_target_accepts_repo_shapes(tmp_path):
    assert audit.resolve_target("owner/repo") == ("https://github.com/owner/repo.git", "owner/repo")
    assert audit.resolve_target("https://github.com/owner/repo/tree/main")[1] == "owner/repo"
    with pytest.raises(ValueError):
        audit.resolve_target("not a repo")


def test_stale_page_has_product_evidence_and_quiet_page_does_not(repo):
    commits = audit.read_history(repo)
    docs = audit.head_docs(repo)
    pages = {p["path"]: p for p in audit.analyze_pages(commits, docs, audit.read_doc_texts(repo, docs), NOW, 180)}
    assert pages["docs/export.md"]["status"] == "stale"
    assert pages["docs/export.md"]["relevant_since"] >= 3
    assert pages["docs/export.md"]["evidence"]
    assert pages["docs/about.md"]["status"] == "quiet"
    assert pages["docs/new.md"]["status"] == "fresh"


def test_features_coverage_momentum_and_cards(repo):
    a = audit.audit(str(repo), use_judge=False)
    feats = {f["term"]: f for f in a["features"]}
    assert feats["--format"]["covered"] is False
    kinds = {c["kind"] for c in a["cards"]}
    assert {"document", "refresh", "automate", "quickstart"} <= kinds
    assert "content" not in kinds  # momentum now raises a score in `next` instead of making its own card
    items = a["next"]["items"]
    assert items and [i["rank"] for i in items] == list(range(1, len(items) + 1))
    assert any(i["kind"] == "refresh" and i["path"] == "docs/export.md" for i in items)
    assert a["release"]["name"] == "v1.1" and a["release"]["previous"] == "v1.0"
    notes = a["drafts"]["release_notes"]
    assert "## New" in notes and "--format" in notes and "bump deps" not in notes
    assert a["summary"]["pages"] == 4


def test_save_and_publish_upsert_one_row(repo, tmp_path):
    a = audit.audit(str(repo), use_judge=False)
    md = audit.save(a, tmp_path / "out")
    assert md.read_text(encoding="utf-8").startswith("# Docs audit")
    site = tmp_path / "audits"
    audit.publish(a, site)
    audit.publish(a, site)
    rows = json.loads((site / "index.json").read_text(encoding="utf-8"))["audits"]
    assert len(rows) == 1 and rows[0]["stale"] == a["summary"]["stale"]
    assert json.loads((site / f"{a['id']}.json").read_text(encoding="utf-8"))["repo"] == a["repo"]


def test_judge_sort_without_a_judge_is_empty(monkeypatch):
    monkeypatch.setattr(audit.judge, "available", lambda: False)
    assert audit.judge_sort(["something"]) == {}


def test_judge_sort_keeps_only_a_confident_answer(monkeypatch):
    monkeypatch.setattr(audit.judge, "available", lambda: True)
    monkeypatch.setattr(audit.judge, "ask", lambda items, q, timeout=0: [
        {"kind": {"feature": 0.9, "fix": 0.05, "docs": 0.03, "internal": 0.02}},
        {"kind": {"feature": 0.4, "fix": 0.3, "docs": 0.2, "internal": 0.1}},
        None])
    assert audit.judge_sort(["a", "b", "c"]) == {0: "feature"}


def test_title_skips_html_and_falls_back_to_the_file_name():
    assert audit._title("# <style>\n", "docs/index.md") == "Index"
    assert audit._title("---\ntitle: Export data\n---\n", "docs/x.md") == "Export data"
    assert audit._title("# Use `--format`\n", "docs/x.md") == "Use --format"


def test_internal_docs_are_not_user_pages():
    assert not audit.is_doc_path("docs/internal/plan.md")
    assert not audit.is_doc_path("docs/2026-06-23-tui-adr.md")
    assert not audit.is_doc_path("docs/RELEASING.md")
    assert audit.is_doc_path("docs/configure/commands.md")


def test_repo_name_never_marks_a_topic(repo):
    commits = audit.read_history(repo)
    pages = {p["path"]: p for p in audit.analyze_pages(commits, ["docs/export.md"], {}, NOW, 180, repo_name="acme/export")}
    assert pages["docs/export.md"]["relevant_since"] == 0


def test_release_range_skips_nightly_tags():
    t = lambda n, d: {"name": n, "date": NOW - timedelta(days=d)}
    commits = [{"sha": "a", "date": NOW - timedelta(days=3), "subject": "feat: x", "files": [], "author": "a", "scope": ""}]
    rel = audit.release_range(commits, [t("v2.0-nightly.1", 1), t("v1.1", 2), t("v1.0", 10)], NOW)
    assert rel["name"] == "v1.1" and rel["previous"] == "v1.0"


def test_issue_lists_cards_and_never_opens_anything(repo):
    a = audit.audit(str(repo), use_judge=False)
    a["url"] = "https://github.com/acme/proj"
    a["repo"] = "acme/proj"
    data = audit.issue(a)
    assert data["title"].startswith("Docs audit:")
    assert "- [ ] **Update Export** (`docs/export.md`)" in data["body"]
    assert "@" not in data["body"].split("<details>")[0]  # logins go in without @, so nobody is pinged
    assert data["commands"] == [f'gh issue create --repo acme/proj --title "{data["title"]}" --body-file issue.md']


def test_publish_keeps_one_audit_per_repo(repo, tmp_path):
    site = tmp_path / "audits"
    a1 = audit.audit(str(repo), use_judge=False)
    audit.publish(a1, site)
    a2 = dict(a1, id=a1["id"] + "-b")
    audit.publish(a2, site)
    rows = json.loads((site / "index.json").read_text(encoding="utf-8"))["audits"]
    assert [r["id"] for r in rows] == [a2["id"]]
    assert not (site / f"{a1['id']}.json").exists()


def test_undocumented_features_in_one_area_become_one_card():
    feats = [{"sha": f"s{i}", "date": "2026-10-0" + str(i + 1), "subject": f"feat(workspace): thing {i}", "pr": None,
              "author": "a", "term": "thing", "area": "workspace", "area_src": "scope", "covered": False,
              "judge": "judge", "closest_page": "docs/cli.md"} for i in range(4)]
    rel = {"name": "v1", "previous": "v0", "date": "2026-10-05", "commits": []}
    cards = audit.build_cards("acme/proj", [], feats, {"workspace": {"commits": 4, "authors": 2}}, rel, "", False, 180)
    docs = [c for c in cards if c["kind"] == "document"]
    assert len(docs) == 1 and docs[0]["title"] == "Document the `workspace` feature" and docs[0]["count"] == 4
    assert "docs/cli.md" in docs[0]["action"]
    assert not [c for c in cards if c["kind"] == "content"]


def test_common_words_never_mark_a_page_stale():
    def c(i, path):
        return {"sha": f"{i:040d}", "date": NOW - timedelta(days=1 + i % 50), "author": "a", "scope": "",
                "subject": f"fix: thing {i}", "files": [path]}
    # 300 product commits, every one touching a "column" file: the word names no topic.
    product = [c(i, f"src/column_{i}.py") for i in range(300)]
    docs_hist = [{"sha": "d" * 40, "date": NOW - timedelta(days=400), "author": "a", "scope": "",
                  "subject": "docs", "files": ["docs/column.md", "docs/rarething.md"]}]
    product[0]["files"] = ["src/rarething.py"]
    pages = {p["path"]: p for p in audit.analyze_pages(docs_hist, ["docs/column.md", "docs/rarething.md"], {}, NOW, 180,
                                                       product_commits=product)}
    assert pages["docs/column.md"]["status"] == "quiet"
    assert pages["docs/rarething.md"]["status"] == "stale"


def test_blog_and_contributing_are_not_docs_pages():
    assert not audit.is_doc_path("website/blog/2024-01-01-post.md")
    assert not audit.is_doc_path("docs/contributing/how.md")


def test_judge_clears_a_stale_page_the_commits_do_not_touch(monkeypatch):
    monkeypatch.setattr(audit.judge, "available", lambda: True)
    monkeypatch.setattr(audit.judge, "ask", lambda items, q, timeout=0: [{"stale": 0.1}, {"stale": 0.9}])
    pages = [{"path": "a.md", "status": "stale", "evidence": [{"subject": "x"}]},
             {"path": "b.md", "status": "stale", "evidence": [{"subject": "y"}]}]
    assert audit.judge_stale(pages, {}) == 1
    assert pages[0]["status"] == "quiet" and pages[1]["status"] == "stale" and pages[1]["judge"] == "judge"


def test_pages_judge_never_read_become_unchecked(monkeypatch):
    monkeypatch.setattr(audit.judge, "available", lambda: True)
    monkeypatch.setattr(audit.judge, "ask", lambda items, q, timeout=0: [{"stale": 0.9} for _ in items])
    monkeypatch.setattr(audit, "JUDGE_STALE_MAX", 40)
    pages = [{"path": f"p{i}.md", "status": "stale", "relevant_since": 100 - i, "evidence": []} for i in range(45)]
    audit.judge_stale(pages, {})
    assert sum(p["status"] == "stale" for p in pages) == 40
    assert sum(p["status"] == "unchecked" for p in pages) == 5


def test_area_card_points_at_the_existing_page():
    feats = [{"sha": f"s{i}", "date": "2026-10-0" + str(i + 1), "subject": f"feat(databricks): thing {i}", "pr": None,
              "author": "a", "term": "thing", "area": "databricks", "area_src": "scope", "covered": False,
              "judge": "judge", "closest_page": "docs/x.md"} for i in range(3)]
    pages = [{"path": "docs/reference/databricks-configs.md", "status": "fresh", "ancient": False}]
    rel = {"name": "v1", "previous": "v0", "date": "2026-10-05", "commits": []}
    card = [c for c in audit.build_cards("acme/proj", pages, feats, {}, rel, "", False, 180) if c["kind"] == "document"][0]
    assert card["title"] == "Document the new `databricks` changes"
    assert "docs/reference/databricks-configs.md" in card["action"]
