"""One place for every setting. No other file names a model."""

from __future__ import annotations

import os
from pathlib import Path

MODEL = "claude-sonnet-5-5"
EFFORT = "medium"

# Sonnet 5.5 list price per million tokens, used for "list price, not billed" cost.
PRICE_INPUT_PER_MTOK = 2.00
PRICE_OUTPUT_PER_MTOK = 10.00
PRICE_CACHE_READ_PER_MTOK = 0.20

# FIRSTRUN_ENV_FILE wins. Otherwise .env in the current folder, then the author's shared key file.
_AUTHOR_ENV = Path(r"D:\Atharva\NOTES\.env")
ENV_FILE = Path(os.environ["FIRSTRUN_ENV_FILE"]) if os.environ.get("FIRSTRUN_ENV_FILE") else (
    Path(".env") if Path(".env").exists() or not _AUTHOR_ENV.exists() else _AUTHOR_ENV
)
RUNS_DIR = Path(os.environ.get("FIRSTRUN_RUNS_DIR", "runs"))
PRECEDENTS_FILE = Path(os.environ.get("FIRSTRUN_PRECEDENTS", "precedents.json"))
SECRETS_ALLOWLIST = Path(os.environ.get("FIRSTRUN_SECRETS", "secrets.allowlist"))

def _default_docker() -> str:
    """Plain docker when it is on PATH. On Windows without it, Docker inside WSL."""
    import shutil
    import sys

    if shutil.which("docker"):
        return "docker"
    if sys.platform == "win32" and shutil.which("wsl"):
        return "wsl -d Ubuntu-22.04 docker"
    return "docker"


DOCKER_CMD = (os.environ.get("FIRSTRUN_DOCKER") or _default_docker()).split()
DEFAULT_IMAGE = "python:3.11-slim"

KEYS = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "TYPESAFE_API_KEY", "FIRECRAWL_API_KEY_1")


_KEYS_SCRIPT = _AUTHOR_ENV.parent / "SCRIPTS" / "keys" / "keys.py"


def _healthy_firecrawl_key() -> str | None:
    """The first Firecrawl slot with credits left, from the author's key rotator. None anywhere else.
    Slots burn in order, so slot 1 alone goes dead after a busy day."""
    if not _KEYS_SCRIPT.exists():
        return None
    import subprocess
    import sys

    try:
        p = subprocess.run([sys.executable, str(_KEYS_SCRIPT), "firecrawl"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    key = p.stdout.strip().splitlines()[-1].strip() if p.returncode == 0 and p.stdout.strip() else ""
    return key if key.startswith("fc-") else None


def load_env(path: Path | None = None) -> None:
    """Load KEY=VALUE lines into os.environ at run time. Never overwrites a set value."""
    path = path or ENV_FILE
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value
    if "FIRECRAWL_API_KEY" not in os.environ:
        key = _healthy_firecrawl_key() or os.environ.get("FIRECRAWL_API_KEY_1")
        if key:
            os.environ["FIRECRAWL_API_KEY"] = key
    # The Agent SDK must use the subscription token, never an API key.
    os.environ.pop("ANTHROPIC_API_KEY", None)


# --- model call guard ---------------------------------------------------------

import contextlib  # noqa: E402

_blocked = 0


class ModelCallBlocked(RuntimeError):
    """A model call was attempted while model calls are blocked (the verification run)."""


@contextlib.contextmanager
def block_model_calls():
    """Inside this block every Claude or Jev call raises ModelCallBlocked."""
    global _blocked
    _blocked += 1
    try:
        yield
    finally:
        _blocked -= 1


def assert_model_call_allowed(what: str = "model call") -> None:
    if _blocked:
        raise ModelCallBlocked(f"{what} blocked: model calls are not allowed during verification")
