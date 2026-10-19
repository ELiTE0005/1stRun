"""Add the team map and the ranked "What to Ship Next" list to audit boards that were published before both existed.

Each board in docs/audits/audit-*.json gets two new keys, `team` and `next`, built from the repo's git history at the
commit the audit read (history.head, or the last commit before generated_at). Nothing else in the board changes: not
the cards, not the summary, not index.json, not the receipts. No Jev call is made, so no count moves.

    python scripts/audit_team_backfill.py                 # dry run: print what each board would get
    python scripts/audit_team_backfill.py --out <dir>     # dry run, and write <id>.team-next.json per board to <dir>
    python scripts/audit_team_backfill.py --apply         # write the two keys into the boards
    python scripts/audit_team_backfill.py --apply --only <id> --force   # redo one board, for example after an opt-out

Needs git and network. GITHUB_TOKEN, GH_TOKEN or `gh auth token` adds GitHub logins and avatars; --no-github skips that.
Do not run --apply while scripts/audit_cost_estimates.py --apply runs: both rewrite whole board files.
"""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from firstrun import audit as audit_mod, team as team_mod  # noqa: E402

SITE = ROOT / "docs" / "audits"
NEW = {"team", "next"}


def rev_before(repo: Path, when: str) -> str:
    p = subprocess.run(["git", "-C", str(repo), "rev-list", "-1", f"--before={when}", "HEAD"], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    sha = p.stdout.strip()
    if p.returncode != 0 or not sha:
        raise RuntimeError(f"no commit before {when} in {repo}")
    return sha


def backfill_board(board: dict, repo_path: Path, docs_path: Path | None = None, github: bool = True,
                   optout: dict | None = None) -> dict:
    """A copy of the board with `team` and `next` built as of its audit. Raises when anything else would change."""
    as_of = datetime.fromisoformat(board["generated_at"]).astimezone(timezone.utc)
    rev = (board.get("history") or {}).get("head") or rev_before(repo_path, board["generated_at"])
    commits = audit_mod.read_history(repo_path, rev)
    tags = [t for t in audit_mod.read_tags(repo_path) if t["date"] <= as_of + timedelta(hours=1)]
    docs = None
    if docs_path:
        drev = rev_before(docs_path, board["generated_at"])
        docs = {"repo": docs_path, "rev": drev, "commits": audit_mod.read_history(docs_path, drev)}
    rel = audit_mod.release_range(commits, tags, as_of)
    name = (board.get("release") or {}).get("name") or ""
    release = {"tagger": next((t.get("tagger") or "" for t in tags if t["name"] == name), ""),
               "shas": [c["sha"] for c in rel["commits"]] if rel["name"] == name else []}
    mom = audit_mod.momentum(commits, as_of, board.get("features") or [])
    cl = audit_mod.changelog_recent(commits, as_of)
    base = {k: v for k, v in board.items() if k not in NEW}
    b2 = copy.deepcopy(base)
    audit_mod.team_and_next(b2, {"repo": repo_path, "rev": rev, "commits": commits}, as_of, mom, cl, docs=docs,
                            release=release, github=github, optout=optout)
    if set(b2) - set(base) - NEW or any(b2.get(k) != v for k, v in base.items()):
        raise RuntimeError(f"{board['id']}: the backfill would change more than team and next")
    return b2


def summary(b: dict) -> list[str]:
    t, n = b.get("team") or {}, b.get("next") or {}
    people = {p["id"]: p for p in t.get("people") or []}
    areas = {a["id"]: a for a in t.get("areas") or []}
    out = [f"{b['repo']}" + (f" (docs in {b['docs_repo']})" if b.get("docs_repo") else "") + f"  [{b['id']}]"]
    if t.get("disabled"):
        out.append(f"  team: disabled ({t['disabled']})")
    elif t:
        out.append(f"  team: {len(people)} people on the map, {t['total_people']} in total, {t['commits']} commits, "
                   f"{t['bots_skipped']} bot commits skipped, source {t['source']}")
        for p in list(people.values())[:3]:
            top = areas.get(p.get("top")) or {}
            out.append(f"    {p['id']} {p['name']} (@{p['login'] or '-'}): {p['commits']} commits, share {p['share']}, "
                       f"works most on {top.get('label', '-')} ({p['top_share']})")
        out.append("  areas: " + ", ".join(f"{a['label']} [{a['path']}] {a['share']}" for a in areas.values()))
        single = [a for a in areas.values() if a["single"]]
        if single:
            out.append("  single owner: " + ", ".join(
                f"{a['label']} ({people.get(a['owners'][0]['p'], {}).get('name', 'everyone else')})" for a in single))
    else:
        out.append("  team: none")
    for it in (n.get("items") or [])[:10]:
        who = people.get((it.get("owner") or {}).get("p"))
        out.append(f"  {it['rank']:>2}. [{it['score']:>3}] {it['kind']:<10} {it['effort']} {it['title'][:70]}"
                   + (f"  -> {who['name']}: {it['owner']['why']}" if who else f"  -> no owner. {it.get('fallback') or ''}"))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Write team and next into the boards.")
    ap.add_argument("--only", help="One audit id.")
    ap.add_argument("--force", action="store_true", help="Rebuild boards that already have team and next.")
    ap.add_argument("--no-github", action="store_true", help="Skip the GitHub login lookup.")
    ap.add_argument("--out", type=Path, help="Dry run output: write <id>.team-next.json per board into this folder.")
    args = ap.parse_args()
    optout = team_mod.load_optout(SITE / "team-optout.json")
    todo = []
    for p in sorted(SITE.glob("audit-*.json")):
        board = json.loads(p.read_text(encoding="utf-8"))
        if board.get("mode") == "sitemap" or (args.only and board["id"] != args.only):
            continue
        if NEW <= set(board) and not args.force:
            print(f"skip {board['id']}: it already has team and next (add --force)")
            continue
        todo.append((p, board))
    failed = 0
    for p, board in todo:
        tmp = Path(tempfile.mkdtemp(prefix="firstrun-backfill-"))
        try:
            repo = audit_mod.clone(audit_mod.resolve_target(board["repo"])[0], tmp / "repo")
            docs = audit_mod.clone(audit_mod.resolve_target(board["docs_repo"])[0], tmp / "docs") if board.get("docs_repo") else None
            b2 = backfill_board(board, repo, docs, github=not args.no_github, optout=optout)
            print("\n".join(summary(b2)))
            extra = {k: b2[k] for k in ("team", "next") if k in b2}
            print(f"  size: team {len(json.dumps(extra.get('team'), separators=(',', ':')))} B, "
                  f"next {len(json.dumps(extra.get('next'), separators=(',', ':')))} B")
            if args.out:
                args.out.mkdir(parents=True, exist_ok=True)
                (args.out / f"{board['id']}.team-next.json").write_text(json.dumps(extra, indent=1, ensure_ascii=False),
                                                                         encoding="utf-8")
            if args.apply:
                p.write_text(json.dumps(b2, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
                print(f"  wrote {p.name}")
        except Exception as e:  # noqa: BLE001 - one broken board must not stop the rest
            failed += 1
            print(f"FAILED {board['id']}: {e}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    if not args.apply:
        print("\ndry run. Add --apply to write.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
