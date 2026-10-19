"""audit: stop suggesting docs work a maintainer rejects. Cases come from entireio/cli, 2026-10-12, 9 issues closed."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from firstrun import audit, nextup

NOW = datetime.now(timezone.utc)


def _c(i: int, subject: str, files: list[str], days: int = 5) -> dict:
    return {"sha": f"{i:040d}", "date": NOW - timedelta(days=days), "author": "a", "scope": "", "subject": subject,
            "files": files}


def _feats(commits: list[dict], corpus: str = "", texts: dict | None = None, sources=None, head_files=None) -> list[dict]:
    return audit.find_features(commits, NOW, corpus, False, texts or {}, sources=sources, head_files=head_files)


def _feat(i: int, subject: str, area: str, src: str, files: list[str]) -> dict:
    return {"sha": f"s{i}", "date": f"2026-10-0{i + 1}", "subject": subject, "pr": None, "author": "a", "term": "x",
            "area": area, "area_src": src, "covered": False, "judge": "text", "closest_page": "", "files": files}


REL = {"name": "v1", "previous": "v0", "date": "2026-10-05", "commits": []}


def _cards(feats, pages=None, corpus="", repo="entireio/cli"):
    return audit.build_cards(repo, pages or [], feats, {}, REL, "", False, 180, md_corpus=corpus)


# ----------------------------------------------------------------------------- F1 hidden and internal

def test_f1_subject_that_says_hidden_is_dropped():
    commits = [_c(1, "Add hidden `entire checkpoint create` for snapshot checkpoints", ["cmd/cli/checkpoint_create.go"]),
               _c(2, "feat: add `--format` flag to export", ["cmd/cli/export.go"])]
    assert [f["term"] for f in _feats(commits)] == ["--format"]


def test_f1_internal_and_experimental_subjects_are_dropped():
    commits = [_c(1, "feat(strategy): internal hook for condensation", ["cmd/cli/strategy/hook.go"]),
               _c(2, "feat: experimental `--turbo` mode", ["cmd/cli/turbo.go"])]
    assert _feats(commits) == []


def test_f1_cobra_hidden_command_in_the_changed_file_is_dropped():
    src = 'cmd := &cobra.Command{\n\tUse:    "create",\n\tShort:  "make one",\n\tHidden: true,\n}\n'
    commits = [_c(1, "Add `entire checkpoint create` for snapshots", ["cmd/cli/agent_help_cmd.go"])]
    assert _feats(commits, sources=lambda paths: {p: src for p in paths}) == []


def test_f1_hidden_marker_for_another_command_does_not_drop_the_feature():
    src = 'cmd := &cobra.Command{\n\tUse:    "debug",\n\tHidden: true,\n}\n'
    commits = [_c(1, "Add `entire export` with --json", ["cmd/cli/export.go"])]
    assert len(_feats(commits, sources=lambda paths: {p: src for p in paths})) == 1


def test_f1_click_typer_and_argparse_markers_are_dropped():
    commits = [_c(1, "feat: add `warm` command", ["src/app/warm.py"])]
    for src in ('@app.command("warm", hidden=True)\ndef warm(): ...\n',
                'p = sub.add_parser("warm", help=argparse.SUPPRESS)\n'):
        assert _feats(commits, sources=lambda paths, s=src: {p: s for p in paths}) == []


def test_f1_hidden_marker_with_no_command_name_drops_the_feature():
    commits = [_c(1, "feat: add `warm` command", ["src/app/warm.py"])]
    assert _feats(commits, sources=lambda paths: {p: "x = dict(hidden=True)\n" for p in paths}) == []


def test_f1_internal_plumbing_area_is_dropped():
    commits = [_c(1, "feat: record turn end", ["cmd/entire/cli/lifecycle.go"]),
               _c(2, "feat: add `--format` flag", ["cmd/entire/cli/export.go"])]
    assert [f["area"] for f in _feats(commits)] == ["export"]


def test_f1_internal_folder_is_dropped_unless_the_whole_repo_lives_there():
    commits = [_c(1, "feat: add widget cache", ["internal/widgetcache/cache.go"]),
               _c(2, "feat: add `--format` flag", ["cmd/export.go"]),
               _c(3, "feat: add `--json` flag", ["cmd/export.go"]),
               _c(4, "feat: add `--csv` flag", ["cmd/export.go"])]
    assert len(_feats(commits)) == 3
    allin = [_c(1, "feat: add widget cache", ["internal/widgetcache/cache.go"]),
             _c(2, "feat: add `--json` flag", ["internal/export/export.go"])]
    assert len(_feats(allin)) == 2


# ----------------------------------------------------------------------------- F2 clusters

def test_f2_file_stem_cluster_with_unrelated_commands_forms_no_page_item():
    subjects = ["Add `entire trail merge` with --force gate bypass", "Add hidden `entire checkpoint create`",
                "Add `entire cluster list` for the cluster catalog", "Add top-level 'entire clone' command"]
    feats = [_feat(i, s, "agent_help_cmd", "file", ["cmd/cli/agent_help_cmd.go"]) for i, s in enumerate(subjects)]
    titles = [c["title"] for c in _cards(feats)]
    assert not any("agent_help_cmd" in t for t in titles)
    assert len([t for t in titles if t.startswith("Document: ")]) == 4  # each stands alone


def test_f2_file_stem_cluster_naming_its_word_still_forms():
    feats = [_feat(i, s, "export", "file", ["src/export.py"]) for i, s in
             enumerate(["Add export to csv", "Add export to json", "Add export to parquet"])]
    assert any(c["title"] == "Document the `export` feature" for c in _cards(feats))


def test_f2_conventional_scope_cluster_still_forms():
    feats = [_feat(i, f"feat(search): thing {i}", "search", "scope", ["src/s.py"]) for i in range(3)]
    assert any(c["title"] == "Document the `search` feature" for c in _cards(feats))


# ----------------------------------------------------------------------------- F3 already documented

def test_f3_area_the_readme_already_covers_forms_no_page_item():
    feats = [_feat(i, f"feat(auth): thing {i}", "auth", "scope", ["cmd/auth.go"]) for i in range(4)]
    readme = "# entire\n\n## headless & ci authentication\n\nrun `entire auth login --token` in ci.\n"
    assert not any("auth" in c["title"] and c["title"].startswith("Document the") for c in _cards(feats, corpus=readme))
    assert any(c["title"] == "Document the `auth` feature" for c in _cards(feats))  # no corpus, so it still shows


def test_f3_contributor_docs_are_never_the_target_page():
    feats = [_feat(i, f"feat(agent): thing {i}", "agent", "scope", ["cmd/agent.go"]) for i in range(3)]
    for path in ("docs/architecture/agent-guide.md", "docs/development/agent-notes.md", "CONTRIBUTING.md"):
        pages = [{"path": path, "status": "fresh", "ancient": False}]
        card = [c for c in _cards(feats, pages) if c["kind"] == "document"][0]
        assert card["title"] == "Document the `agent` feature" and path not in card["action"]


def test_f3_contributor_docs_are_never_the_closest_page():
    commits = [_c(1, "feat: add `--format` flag to export", ["src/export.py"])]
    texts = {"docs/development/cli-conventions.md": "export format flags are described here",
             "docs/guide.md": "export format"}
    assert _feats(commits, texts=texts)[0]["closest_page"] == "docs/guide.md"
    only = {"docs/development/cli-conventions.md": "export format"}
    assert _feats(commits, texts=only)[0]["closest_page"] == ""


def test_f3_every_markdown_file_counts_as_coverage(tmp_path):
    r = tmp_path / "proj"
    r.mkdir()
    subprocess.run(["git", "init", "-q", str(r)], check=True)

    def commit(files, msg, days):
        for n, t in files.items():
            (r / n).parent.mkdir(parents=True, exist_ok=True)
            (r / n).write_text(t, encoding="utf-8")
        when = (NOW - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        env = {**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when, "GIT_AUTHOR_NAME": "a",
               "GIT_AUTHOR_EMAIL": "a@x", "GIT_COMMITTER_NAME": "a", "GIT_COMMITTER_EMAIL": "a@x"}
        subprocess.run(["git", "-C", str(r), "add", "-A"], check=True, env=env)
        subprocess.run(["git", "-C", str(r), "commit", "-q", "-m", msg], check=True, env=env)

    commit({"README.md": "# Proj\n", "src/export.py": "x=1\n", "CONTRIBUTING.md": "Pass `--format` to export.\n",
            "CHANGELOG.md": "- add `--csv` flag\n"}, "initial", 100)
    commit({"src/export.py": "x=2\n"}, "feat: add `--format` flag to export", 5)
    commit({"src/export.py": "x=3\n"}, "feat: add `--csv` flag to export", 4)
    feats = {f["term"]: f for f in audit.audit(str(r), use_jev=False, team=False)["features"]}
    assert feats["--format"]["covered"] is True   # a contributing guide documents it
    assert feats["--csv"]["covered"] is False     # the changelog restates the commit and proves nothing


# ----------------------------------------------------------------------------- F4 release notes

def _release_repo(tmp_path, changelog: str) -> Path:
    r = tmp_path / "rel"
    r.mkdir()
    subprocess.run(["git", "init", "-q", str(r)], check=True)

    def commit(files, msg, days, tag=None):
        for n, t in files.items():
            (r / n).write_text(t, encoding="utf-8")
        when = (NOW - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        env = {**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when, "GIT_AUTHOR_NAME": "a",
               "GIT_AUTHOR_EMAIL": "a@x", "GIT_COMMITTER_NAME": "a", "GIT_COMMITTER_EMAIL": "a@x"}
        subprocess.run(["git", "-C", str(r), "add", "-A"], check=True, env=env)
        subprocess.run(["git", "-C", str(r), "commit", "-q", "-m", msg], check=True, env=env)
        if tag:
            subprocess.run(["git", "-C", str(r), "tag", "-a", tag, "-m", tag], check=True, env=env)

    commit({"README.md": "# P\n", "app.py": "x=1\n"}, "initial", 100, "v0.11.3")
    commit({"app.py": "x=2\n"}, "fix: a thing", 10)
    commit({"app.py": "x=3\n", "CHANGELOG.md": changelog}, "fix: another thing", 3, "v0.11.4")
    return r


def test_f4_release_item_skipped_when_the_changelog_names_the_release(tmp_path):
    a = audit.audit(str(_release_repo(tmp_path, "# Changelog\n\n## v0.11.4\n- fixes\n")), use_jev=False, team=False)
    assert a["release"]["in_changelog"] is True
    assert not [c for c in a["cards"] if c["kind"] == "automate"]
    assert not [i for i in a["next"]["items"] if i["kind"] == "release"]


def test_f4_release_item_stays_when_the_changelog_lacks_the_release(tmp_path):
    a = audit.audit(str(_release_repo(tmp_path, "# Changelog\n\n## v0.11.3\n- old\n")), use_jev=False, team=False)
    assert a["release"]["in_changelog"] is False
    assert [i for i in a["next"]["items"] if i["kind"] == "release"]


def test_f4_changelog_match_is_exact_to_the_version():
    assert audit.changelog_names_release("## [0.11.4] - 2026-10-06", "v0.11.4")
    assert not audit.changelog_names_release("## v0.11.40", "v0.11.4")
    assert not audit.changelog_names_release("## [Unreleased]", "Unreleased")


def test_f4_an_old_board_flag_also_skips_the_item():
    board = {"cards": [{"kind": "automate", "title": "Release notes for v1 are ready to edit", "evidence": []}],
             "release": {"name": "v1", "previous": "v0", "date": "2026-10-05", "commits": 5, "in_changelog": True}}
    assert nextup.candidates(board, NOW.date(), {}, False) == []


# ----------------------------------------------------------------------------- F5 duplicates

def _item(title: str, score_part: float) -> dict:
    return {"kind": "document", "title": title, "parts": {"impact": score_part, "urgency": 0.5, "evidence": 0.5,
                                                          "judged": 0.5}, "effort": "M", "_newest": "2026-10-01"}


def test_f5_rank_never_emits_two_items_with_the_same_title():
    out = nextup.rank([_item("Write a page for auth", 0.5), _item("Write a page for  Auth ", 0.9),
                       _item("Write a page for repo", 0.4)])
    assert [i["title"] for i in out] == ["Write a page for  Auth ", "Write a page for repo"]
    assert [i["rank"] for i in out] == [1, 2]


# ----------------------------------------------------------------------------- G1 code identifiers

def test_g1_subject_naming_only_a_code_identifier_is_dropped():
    commits = [_c(1, "Add getTemporaryStore helper to dedup store access", ["cmd/cli/store.go"]),
               _c(2, "feat: add `--format` flag to export", ["cmd/cli/export.go"]),
               _c(3, "feat: add max_retries setting", ["cmd/cli/retry.go"]),
               _c(4, "feat: add `entire sync` command with a runSync helper", ["cmd/cli/sync.go"])]
    assert sorted(f["area"] for f in _feats(commits)) == ["export", "retry", "sync"]


# ----------------------------------------------------------------------------- G2 command definition file

_TRAIL = 'cmd := &cobra.Command{\n\tUse:    cmdTrail,\n\tShort:  "Manage trails",\n\tHidden: true,\n}\n'


def test_g2_hidden_command_in_its_definition_file_drops_a_feature_that_changed_other_files():
    commits = [_c(1, "Add selectable trail backend", ["cmd/cli/api/client.go", "cmd/cli/api/trail_json.go"])]
    tree = ["cmd/cli/trail_cmd.go", "cmd/cli/trail_cmd_test.go", "cmd/cli/api/client.go", "cmd/cli/api/trail_json.go"]
    seen = {}

    def read(paths):
        seen.update(dict.fromkeys(paths))
        return {p: (_TRAIL if p == "cmd/cli/trail_cmd.go" else "") for p in paths}

    assert _feats(commits, sources=read, head_files=tree) == []
    assert "cmd/cli/trail_cmd.go" in seen


def test_g2_definition_file_check_needs_the_command_in_the_subject():
    tree = ["cmd/cli/trail_cmd.go", "cmd/cli/export_cmd.go", "cmd/cli/api/client.go"]

    def read(paths):
        return {p: (_TRAIL if p == "cmd/cli/trail_cmd.go" else 'Use: "export",\n') for p in paths}

    commits = [_c(1, "Add selectable export backend", ["cmd/cli/api/client.go"])]
    assert len(_feats(commits, sources=read, head_files=tree)) == 1


# ----------------------------------------------------------------------------- G3 command roots

MIRROR = ["Add `entire repo mirror create` onboarding wizard", "Add `repo mirror list --show-available`",
          "Add `repo mirror collaborators` add/remove/list"]


def _mirror_feats():
    return [_feat(i, s, "repo_mirror", "file", ["cmd/cli/repo_mirror.go"]) for i, s in enumerate(MIRROR)]


def _doc_titles(cards):
    return [c["title"] for c in cards if c["kind"] == "document"]


def test_g3_items_with_one_command_root_become_one_question():
    titles = _doc_titles(_cards(_mirror_feats()))
    assert titles == ["Document: Add `repo mirror collaborators` add/remove/list"]  # the newest; the rest fold in


def test_g3_documented_root_drops_the_item_when_the_subcommand_is_in_the_corpus():
    corpus = "## repositories\nrun `entire repo mirror create` then `entire repo mirror list`.\n"
    feats = [_feat(0, MIRROR[0], "repo_mirror", "file", ["cmd/cli/repo_mirror.go"])]
    assert _doc_titles(_cards(feats, corpus=corpus)) == []


def test_g3_documented_root_keeps_an_item_that_names_a_new_flag_or_subcommand():
    corpus = "## repositories\nrun `entire repo mirror create` then `entire repo mirror list`.\n"
    flag = [_feat(0, MIRROR[1], "repo_mirror", "file", ["cmd/cli/repo_mirror.go"])]
    sub = [_feat(0, MIRROR[2], "repo_mirror", "file", ["cmd/cli/repo_mirror.go"])]
    assert len(_doc_titles(_cards(flag, corpus=corpus))) == 1
    assert len(_doc_titles(_cards(sub, corpus=corpus))) == 1
