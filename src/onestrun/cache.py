"""Reuse a recent verified or passed run of the same source, so a repeat spends nothing."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from onestrun import config

REUSABLE = {"verified", "passed"}


def normalize(source: str) -> str:
    """Lowercase scheme and host, drop trailing slash, query and fragment. Local paths resolve."""
    source = (source or "").strip()
    parts = urlsplit(source)
    if parts.scheme in ("http", "https") and parts.netloc:
        path = parts.path.rstrip("/")
        return f"{parts.scheme.lower()}://{parts.netloc.lower()}{path}"
    try:
        return str(Path(source).resolve()).lower()
    except OSError:
        return source.lower()


def _max_age(max_age_hours: float) -> float:
    raw = os.environ.get("ONESTRUN_CACHE_HOURS")
    if raw is not None and raw.strip() != "":
        try:
            return float(raw)
        except ValueError:
            pass
    return max_age_hours


def _parse(stamp: str) -> datetime | None:
    try:
        when = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def find_recent(url: str, max_age_hours: float = 24) -> str | None:
    """Newest run id for this source that is verified or passed and finished in time, else None."""
    hours = _max_age(max_age_hours)
    if hours <= 0:
        return None
    want = normalize(url)
    now = datetime.now(timezone.utc)
    best: tuple[datetime, str] | None = None
    for path in Path(config.RUNS_DIR).glob("*/state.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or str(data.get("status")) not in REUSABLE:
            continue
        finished = _parse(data.get("finished_at", ""))
        if finished is None or (now - finished).total_seconds() > hours * 3600:
            continue
        if normalize(str(data.get("source_url", ""))) != want:
            continue
        if best is None or finished > best[0]:
            best = (finished, path.parent.name)
    return best[1] if best else None


def describe(run_id: str) -> str:
    """The one-line `cached:` message for a run."""
    run_dir = Path(config.RUNS_DIR) / run_id
    data = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    finished = _parse(data.get("finished_at", "")) or datetime.now(timezone.utc)
    minutes = max(0, int((datetime.now(timezone.utc) - finished).total_seconds() // 60))
    statuses = data.get("step_status") or {}
    passed = sum(1 for v in statuses.values() if v == "passed")
    total = len(statuses)
    try:
        total = len(json.loads((run_dir / "runbook.json").read_text(encoding="utf-8")).get("steps", [])) or total
    except (OSError, ValueError):
        pass
    return (f"cached: tested {minutes} min ago, {data.get('status')}, {passed}/{total} steps "
            "(use --fresh to run again)")
