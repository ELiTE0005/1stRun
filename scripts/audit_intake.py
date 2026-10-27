"""Run by .github/workflows/audit-request.yml. Turns an audit-request issue into a board on the doc-audit log.

Reads ISSUE_BODY, ISSUE_LABELS (comma separated) and EVENT_LABEL from the environment, never from argv,
so issue text never reaches a shell. Writes `id`, `repo`, `message` and `publish` to GITHUB_OUTPUT.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from onestrun import audit as audit_mod, config, intake, tracing  # noqa: E402

SITE_DIR = Path(__file__).resolve().parents[1] / "docs" / "audits"


def out(**kv: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    lines = []
    for k, v in kv.items():
        lines.append(f"{k}<<EOF_INTAKE\n{v}\nEOF_INTAKE")
    text = "\n".join(lines) + "\n"
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)
    print(text)


def from_gist(gid: str) -> dict:
    p = subprocess.run(["gh", "api", f"gists/{gid}"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise ValueError("the gist could not be read")
    files = json.loads(p.stdout).get("files") or {}
    f = next((f for f in files.values() if str(f.get("filename", "")).endswith(".json")), None)
    if not f:
        raise ValueError("the gist has no .json file")
    if (f.get("size") or 0) > intake.MAX_BYTES:
        raise ValueError("the audit is larger than 3 MB")
    text = f.get("content") or ""
    raw = str(f.get("raw_url") or "")
    if f.get("truncated") and raw.startswith("https://gist.githubusercontent.com/"):
        with urllib.request.urlopen(raw, timeout=30) as r:  # noqa: S310 - fixed https host checked above
            text = r.read(intake.MAX_BYTES + 1).decode("utf-8")
    return intake.validate(json.loads(text))


def main() -> int:
    """Start tracing, then run the intake. The workflow passes the Langfuse keys; without them this is a no-op."""
    config.load_env()
    tracing.init_tracing(tags=["audit-intake"])
    try:
        return _intake()
    finally:
        tracing.close_tracing()


def _intake() -> int:
    fields = intake.parse_issue(os.environ.get("ISSUE_BODY", ""))
    labels = {x.strip() for x in os.environ.get("ISSUE_LABELS", "").split(",") if x.strip()}
    event_label = os.environ.get("EVENT_LABEL", "")
    repo, gid = fields["repo"], fields["gist"]

    if gid:
        if "publish" not in labels:
            out(publish="no", message=(
                f"Thanks. This offers a private audit of `{repo or 'your repo'}` for the public log. "
                "A maintainer reads the gist and adds the `publish` label to put it on the board."))
            return 0
        try:
            doc = from_gist(gid)
        except (ValueError, json.JSONDecodeError) as e:
            out(publish="no", message=f"The submission could not be published: {e}.")
            return 0
        audit_mod.publish(doc, SITE_DIR)
        out(publish="yes", id=doc["id"], repo=doc["repo"],
            message=f"Published. The board for `{doc['repo']}` is at {intake.SITE}?id={doc['id']}")
        return 0

    if event_label and event_label != "audit-request":
        out(publish="no", message="")
        return 0
    if not repo:
        out(publish="no", message="The issue names no repo. Write it as owner/repo, for example fastapi/typer.")
        return 0
    try:
        result = audit_mod.audit(repo, 180, use_judge=True, team=fields["team"])
    except (RuntimeError, ValueError) as e:
        msg = str(e)
        if "clone failed" in msg:
            msg = (f"1stRun could not clone `{repo}`. If it is private, run "
                   f"`1stRun audit {repo}` on your machine, then `1stRun audit-submit` to offer it for the log.")
        out(publish="no", message=f"The audit did not finish: {msg}")
        return 0
    audit_mod.publish(result, SITE_DIR)
    s = result["summary"]
    out(publish="yes", id=result["id"], repo=result["repo"], message=(
        f"Done. `{result['repo']}`: {s['pages']} docs pages, {s['stale']} stale, "
        f"{s['uncovered']} recent features with no docs, {s['cards']} cards.\n\n"
        f"Board: {intake.SITE}?id={result['id']} (live about a minute after this comment)."))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
