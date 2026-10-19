"""Track T4. The ask-once store, precedents.json, keyed by error signature."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from firstrun import config
from firstrun.models import FailureClass


def _read() -> dict:
    path = config.PRECEDENTS_FILE  # read at call time so tests can patch it
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    if isinstance(data, dict):
        return data
    _move_aside(path)  # corrupt or empty: keep it for a human, start a new file
    return {}


def _move_aside(path) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    try:
        path.replace(path.with_name(f"{path.name}.corrupt-{stamp}"))
    except OSError:
        pass


def lookup(signature: str) -> FailureClass | None:
    entry = _read().get(signature)
    if not isinstance(entry, dict):
        return None
    try:
        return FailureClass(entry.get("class"))
    except ValueError:
        return None


def store(signature: str, cls: FailureClass, example: str = "") -> None:
    data = _read()
    data[signature] = {
        "class": FailureClass(cls).value,
        "stored_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "example": example[:200],
    }
    path = config.PRECEDENTS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
