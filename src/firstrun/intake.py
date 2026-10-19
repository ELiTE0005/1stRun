"""Get an audit onto the public doc-audit log through a GitHub issue.

A public repo needs only its name: the audit-request workflow clones it and publishes the board.
A private repo is audited on the owner's machine. `firstrun audit-submit` uploads that audit as a
secret gist and opens the issue. The workflow publishes a submission only after a maintainer adds
the `publish` label, because the gist content cannot be checked against a repo it cannot read.
"""

from __future__ import annotations

import re
from urllib.parse import urlencode

LOG_REPO = "HighnessAtharva/firstrun"
TEMPLATE = "audit-request.yml"
SITE = "https://firstrun.atharvashah.com/doc-audit/"
MAX_BYTES = 3_000_000

_REPO = re.compile(r"^(?:https?://github\.com/)?([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")
_GIST = re.compile(r"^https://gist\.github\.com/(?:[\w-]+/)?([0-9a-f]{20,40})/?$")
_FIELD = re.compile(r"^###\s+(.+?)\s*$", re.M)


def repo_name(text: str) -> str:
    """owner/repo from a name or a GitHub URL, or "" when it is neither."""
    m = _REPO.match((text or "").strip())
    if not m or m.group(1) in (".", "..") or m.group(2) in (".", ".."):
        return ""
    return f"{m.group(1)}/{m.group(2)}"


def gist_id(url: str) -> str:
    m = _GIST.match((url or "").strip())
    return m.group(1) if m else ""


def request_url(repo: str) -> str:
    """The prefilled issue that asks the workflow to audit a public repo."""
    q = {"template": TEMPLATE, "title": f"Audit request: {repo}", "repo": repo}
    return f"https://github.com/{LOG_REPO}/issues/new?{urlencode(q)}"


def submission_url(repo: str, gist: str) -> str:
    """The prefilled issue that offers a private audit for the log."""
    q = {"template": TEMPLATE, "title": f"Audit submission: {repo}", "repo": repo, "gist": gist}
    return f"https://github.com/{LOG_REPO}/issues/new?{urlencode(q)}"


def parse_issue(body: str) -> dict:
    """Read the issue form: {"repo": owner/repo or "", "gist": gist id or "", "team": False when the requester
    ticked "Leave out the team map"}."""
    fields: dict[str, str] = {}
    parts = _FIELD.split(body or "")
    for label, value in zip(parts[1::2], parts[2::2]):
        v = value.strip()
        fields[label.strip().lower()] = "" if v in ("_No response_", "None") else v.splitlines()[0].strip() if v else ""
    repo = next((repo_name(v) for k, v in fields.items() if "repo" in k and repo_name(v)), "")
    gist = next((gist_id(v) for k, v in fields.items() if "gist" in k and gist_id(v)), "")
    team = not re.search(r"^\s*-\s*\[[xX]\]\s*Leave out the team map", body or "", re.M)
    return {"repo": repo, "gist": gist, "team": team}


def validate(doc: object) -> dict:
    """Check a submitted audit has the shape the doc-audit page reads. Returns it, or raises ValueError."""
    if not isinstance(doc, dict):
        raise ValueError("the gist does not hold a JSON object")
    for key, kind in (("id", str), ("repo", str), ("generated_at", str), ("summary", dict), ("pages", list),
                      ("cards", list), ("release", dict)):
        if not isinstance(doc.get(key), kind):
            raise ValueError(f"the audit has no {key}")
    if not re.fullmatch(r"audit-[a-z0-9-]{8,120}", doc["id"]):
        raise ValueError("the audit id is not one firstrun audit writes")
    for key in ("pages", "stale", "quiet", "oldest_days", "median_age_days", "features", "uncovered", "cards"):
        if not isinstance(doc["summary"].get(key), int):
            raise ValueError(f"the audit summary has no {key}")
    doc["release"].setdefault("name", "")
    doc.setdefault("url", "")
    for key in ("url", "docs_url"):
        if doc.get(key) and not str(doc[key]).startswith("https://github.com/"):
            doc[key] = ""
    doc["source"] = "submitted"
    from firstrun.team import sanitize

    return sanitize(doc)
