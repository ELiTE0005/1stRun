"""Track T2. Reads and writes runs/<run_id>/state.json and runbook.json."""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from firstrun import config
from firstrun.models import Runbook, RunState


def target_name(source_url: str) -> str:
    """The tool name for a URL: the host without www, or the file stem for a local path."""
    parsed = urlparse(source_url)
    if parsed.scheme in ("", "file") or not parsed.netloc:
        return Path(parsed.path or source_url).stem or "local"
    host = parsed.netloc.split(":")[0].lower()
    return host[4:] if host.startswith("www.") else host


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "run"


def run_dir(run_id: str) -> Path:
    return Path(config.RUNS_DIR) / run_id


def new_run_id(source_url: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_id = f"{stamp}-{_slug(target_name(source_url))}"
    # Two runs of one target in the same second must not share a folder.
    while True:
        try:
            run_dir(run_id).mkdir(parents=True, exist_ok=False)  # the mkdir claims the id
            return run_id
        except FileExistsError:
            run_id = f"{stamp}-{_slug(target_name(source_url))}-{secrets.token_hex(2)}"


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)  # atomic, so a crash never leaves half a file
    return path


def save_state(state: RunState) -> Path:
    return _write(run_dir(state.run_id) / "state.json", state.model_dump_json(indent=2))


def load_state(run_id: str) -> RunState:
    return RunState.model_validate_json((run_dir(run_id) / "state.json").read_text(encoding="utf-8"))


def save_runbook(run_id: str, runbook: Runbook) -> Path:
    return _write(run_dir(run_id) / "runbook.json", runbook.model_dump_json(indent=2))


def load_runbook(run_id: str) -> Runbook:
    return Runbook.model_validate_json((run_dir(run_id) / "runbook.json").read_text(encoding="utf-8"))


def pins_path(run_id: str) -> Path:
    return run_dir(run_id) / "pins.txt"


def save_pins(run_id: str, text: str) -> Path:
    """Package versions seen at the end of the recovery run, one name==version per line."""
    return _write(pins_path(run_id), text)


def load_pins(run_id: str) -> str:
    try:
        return pins_path(run_id).read_text(encoding="utf-8")
    except OSError:
        return ""
