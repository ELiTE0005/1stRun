"""Hand a verified docs patch to the user's own coding agent. FirstRun never opens a PR itself."""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path

from firstrun import docs_source
from firstrun.models import RunState, RunStatus, Runbook

HEADER = "Review the diff below. Run these only after the human says yes."


class NotReady(Exception):
    """The run has no verified patch to hand over."""


def _load(run_dir: Path) -> tuple[RunState, str, str]:
    run_dir = Path(run_dir)
    try:
        state = RunState.model_validate_json((run_dir / "state.json").read_text(encoding="utf-8"))
    except OSError:
        raise NotReady(f"no state.json in {run_dir}")
    if state.status != RunStatus.VERIFIED:
        raise NotReady(f"run {state.run_id} is {state.status.value}, not verified. Only a verified run becomes a PR.")
    diff_p, body_p = run_dir / "patch.diff", run_dir / "pr_body.md"
    if not diff_p.exists() or not body_p.exists():
        raise NotReady(f"run {state.run_id} has no patch.diff and pr_body.md. Nothing to send.")
    return state, diff_p.read_text(encoding="utf-8"), body_p.read_text(encoding="utf-8")


def _markdown(run_dir: Path) -> str:
    try:
        return Runbook.model_validate_json((run_dir / "runbook.json").read_text(encoding="utf-8")).docs_markdown
    except Exception:  # noqa: BLE001 - a missing runbook only weakens the lookup
        return ""


def retarget(diff: str, path: str) -> str:
    """Point the a/ and b/ headers of a one-file diff at the real repo path."""
    out = []
    for line in diff.splitlines(keepends=True):
        if line.startswith("--- a/"):
            line = f"--- a/{path}\n"
        elif line.startswith("+++ b/"):
            line = f"+++ b/{path}\n"
        out.append(line)
    return "".join(out)


def build(run_dir: Path) -> dict:
    """The data behind the text plan and --json. Writes patch.repo.diff when the source is known."""
    run_dir = Path(run_dir)
    state, diff, body = _load(run_dir)
    src = docs_source.find(state.source_url, _markdown(run_dir))
    known = src["how"] != "unknown"
    repo = src["repo"] if known else "OWNER/REPO"
    path = src["path"] if known else "PATH"
    from firstrun.state import target_name

    step = state.patches[0].step_id if state.patches else 0
    slug = re.sub(r"[^a-z0-9]+", "-", target_name(state.source_url).lower()).strip("-") or "docs"
    branch = f"firstrun/fix-{slug}-step{step}"
    title = (body.strip().splitlines() or ["Fix a broken command in the quickstart"])[0].strip()
    repo_diff = retarget(diff, path)
    if known:
        (run_dir / "patch.repo.diff").write_text(repo_diff, encoding="utf-8", newline="")
        diff_file = (run_dir / "patch.repo.diff").resolve().as_posix()
    else:
        diff_file = (run_dir / "patch.diff").resolve().as_posix()
    body_file = (run_dir / "pr_body.md").resolve().as_posix()
    commands = [
        f"gh repo fork {repo} --clone",
        f"cd {repo.split('/')[-1]}",
        f"git checkout -b {branch}",
        f"git apply --whitespace=nowarn {shlex.quote(diff_file)}",
        f"git commit -am {shlex.quote(title)}",
        "git push -u origin HEAD",
        f"gh pr create --repo {repo} --title {shlex.quote(title)} --body-file {shlex.quote(body_file)}",
    ]
    return {"repo": repo, "path": path, "branch": src["branch"], "how": src["how"], "diff": repo_diff,
            "pr_body": body, "commands": commands, "source_url": state.source_url, "run_id": state.run_id}


def plan(run_dir: Path) -> str:
    """A numbered, copy-pasteable command list. Raises NotReady for an unverified run."""
    data = build(run_dir)
    lines = [HEADER, ""]
    if data["how"] == "unknown":
        lines += [
            f"FirstRun could not find the docs source for {data['source_url']}.",
            "Find it first: open the page and follow its \"Edit this page\" link on GitHub.",
            "Then replace OWNER/REPO and PATH below, and set the same PATH in the diff headers before git apply.",
            "",
        ]
    else:
        lines += [f"Docs source: {data['repo']} {data['path']} (found by {data['how']})", ""]
    for i, cmd in enumerate(data["commands"], 1):
        lines.append(f"{i}. {cmd}")
    lines += ["", "Diff:", "", data["diff"].rstrip("\n")]
    return "\n".join(lines) + "\n"


def as_json(run_dir: Path) -> str:
    d = build(run_dir)
    return json.dumps({k: d[k] for k in ("repo", "path", "branch", "diff", "pr_body", "commands")}, indent=2)
