"""Track T5. The docs diff and the draft PR body."""

from __future__ import annotations

import difflib
import re
from pathlib import Path

from firstrun.models import FailureClass, Patch, Runbook, RunState, RunStatus

_PROMPT = re.compile(r"^\s*(?:\$|>)\s+")


def _replace_line(lines: list[str], old: str, new: str) -> bool:
    """Replace `old` with `new` in the first line that holds it. Retry without a shell prompt."""
    for i, line in enumerate(lines):
        if old in line:
            lines[i] = line.replace(old, new, 1)
            return True
    bare = _PROMPT.sub("", old).strip()
    if not bare:
        return False
    for i, line in enumerate(lines):
        body = line.rstrip("\r\n")
        if _PROMPT.sub("", body).strip() == bare:
            prompt = _PROMPT.match(body)
            ending = line[len(body):]
            lead = body[: len(body) - len(body.lstrip())]
            lines[i] = (prompt.group(0) if prompt else lead) + _PROMPT.sub("", new).strip() + ending
            return True
    return False


def make_diff(docs_md: str, patches: list[Patch], path: str = "quickstart.md") -> str:
    """Unified diff of the docs markdown with each patched command replaced."""
    docs_patches = [p for p in patches if p.failure_class != FailureClass.ENVIRONMENT]
    env_patches = [p for p in patches if p.failure_class == FailureClass.ENVIRONMENT]
    if not docs_patches:
        return ""

    text = docs_md
    unplaced: list[Patch] = []
    for p in docs_patches:
        if "\n" in p.old_command and p.old_command in text:
            text = text.replace(p.old_command, p.new_command, 1)
            continue
        lines = text.splitlines(keepends=True)
        if _replace_line(lines, p.old_command, p.new_command):
            text = "".join(lines)
        else:
            unplaced.append(p)

    body = "".join(
        difflib.unified_diff(
            docs_md.splitlines(keepends=True),
            text.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )
    if not body and not unplaced:
        return ""
    out = "".join(f"# step {p.step_id} could not be located in the docs: {p.old_command}\n" for p in unplaced)
    out += body
    if body and not body.endswith("\n"):
        out += "\n"
    if env_patches:
        out += "# Environment fixes, not part of the docs change:\n"
        for p in env_patches:
            out += f"# step {p.step_id}: {p.old_command} -> {p.new_command} ({p.reason})\n"
    return out


def _error_line(state: RunState, step_id: int) -> str:
    for r in state.results:
        if r.step_id == step_id and not r.passed:
            text = (r.stderr or r.stdout).strip().splitlines()
            if text:
                # Drop the runner's own script name, which means nothing to a docs maintainer.
                return re.sub(r"^/tmp/\.fr_step\.sh: line \d+: ", "", text[-1].strip())
    return ""


def make_pr_body(state: RunState, patches: list[Patch], trace_url: str = "", checkpoint_url: str = "",
                 replay_url: str = "", evidence: list[dict] | None = None) -> str:
    docs_patches = [p for p in patches if p.failure_class != FailureClass.ENVIRONMENT] or patches
    first = docs_patches[0] if docs_patches else None
    verified = state.status == RunStatus.VERIFIED
    n_steps = len({r.step_id for r in state.results}) or len(state.step_status)

    lines = ["Fix a broken command in the quickstart", ""]
    lines += ["Hi, thanks for maintaining this project. I found a step in the quickstart that fails in a clean container.", ""]
    if first:
        lines += ["## What broke", "", f"- Step: {first.step_id}", f"- Command: `{first.old_command}`"]
        err = _error_line(state, first.step_id)
        if err:
            lines.append(f"- Error: `{err}`")
        lines += ["", "## The fix", ""]
        for p in docs_patches:
            lines.append(f"- Step {p.step_id}: `{p.old_command}` becomes `{p.new_command}`. {p.reason}")
            if p.source:
                lines.append(f"  Source: {p.source}")
        lines.append("")
    lines += ["## Proof", ""]
    if verified:
        count = f"all {n_steps} steps" if n_steps else "every step"
        lines.append(
            f"Verified: a fresh python:3.11-slim container ran {count} with the patch, no model calls during verification."
        )
    else:
        lines.append("Not verified. The patched runbook did not pass in a fresh container, so treat this fix as a suggestion.")
    if state.time_to_first_success_s is not None:
        lines.append(f"Time to first success: {state.time_to_first_success_s:.0f} seconds.")
    # Public proof a maintainer can open without an account. Links that need a login stay out.
    proof = []
    if replay_url:
        proof.append(f"- [Replay this run step by step]({replay_url}): the failing output, the fix and the clean rerun. "
                     "The link decodes in your browser, and nothing is uploaded.")
    for e in evidence or []:
        if e.get("public") and str(e.get("url", "")).startswith("https://") and e.get("kind") != "pr":
            proof.append(f"- [{e.get('label') or e.get('kind')}]({e['url']})")
    if state.source_url:
        proof.append(f"- Rerun it yourself: `firstrun {state.source_url}`")
    if proof:
        lines += [""] + proof
    links = []
    if trace_url:
        links.append(f"- Trace: {trace_url}")
    if checkpoint_url:
        links.append(f"- Entire checkpoint: {checkpoint_url}")
    if links:
        lines += ["", "## Links", ""] + links
    lines += ["", "Found by FirstRun, an agent that runs quickstarts in a clean container.", ""]
    return "\n".join(lines)


def _docs_path(runbook: Runbook) -> str:
    name = runbook.source_url.rstrip("/").rsplit("/", 1)[-1]
    return name if name.lower().endswith((".md", ".mdx")) else "quickstart.md"


def write_outputs(run_dir: Path, state: RunState, runbook: Runbook, trace_url: str = "") -> list[Path]:
    """Write patch.diff and pr_body.md only for a verified docs patch."""
    if state.status != RunStatus.VERIFIED:
        return []
    diff = make_diff(runbook.docs_markdown, state.patches, _docs_path(runbook))
    if not diff:
        return []
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    diff_path = run_dir / "patch.diff"
    body_path = run_dir / "pr_body.md"
    diff_path.write_text(diff, encoding="utf-8")
    replay, evidence = "", []
    try:  # the replay link is a convenience, so a share failure never blocks the PR body
        from firstrun import share

        replay = share.link_for_run(run_dir)[0]
        evidence = share.build_payload(run_dir).get("evidence", [])
    except Exception:  # noqa: BLE001
        pass
    body_path.write_text(make_pr_body(state, state.patches, trace_url, replay_url=replay, evidence=evidence),
                         encoding="utf-8")
    return [diff_path, body_path]
