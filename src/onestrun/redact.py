"""Redacts secrets from text before it reaches state.json, report.md, spans or an exported trace."""

from __future__ import annotations

import re

MARK = "[REDACTED]"

# Token shapes that are secrets on their own.
_SHAPES = re.compile(
    r"sk-ant-[A-Za-z0-9_\-]{8,}|sk-[A-Za-z0-9_\-]{16,}|gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{16,}|"
    r"xox[abprs]-[A-Za-z0-9\-]{10,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_\-]{20,}|fc-[A-Za-z0-9]{16,}|"
    r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}|"
    r"(?i:bearer)\s+[A-Za-z0-9._\-]{16,}"
)
# NAME=value where NAME ends in KEY, TOKEN, SECRET or PASSWORD.
_ASSIGN = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:API_?KEY|TOKEN|SECRET|PASSWORD|PASSWD)[A-Z0-9_]*)(\s*=\s*)(['\"]?)([^\s'\"]{4,})\3"
)


def _allowlist_values() -> list[str]:
    from onestrun import sandbox

    return [v for v in sandbox._allowlist_env().values() if len(v) >= 6]


def redact(text: str, extra: list[str] | None = None) -> str:
    """Replace secrets in `text`. Exact allowlist values go first, then token shapes, then NAME=value."""
    if not text:
        return text
    for value in sorted([*_allowlist_values(), *(extra or [])], key=len, reverse=True):
        if value and value in text:
            text = text.replace(value, MARK)
    text = _SHAPES.sub(MARK, text)
    return _ASSIGN.sub(lambda m: f"{m.group(1)}{m.group(2)}{MARK}", text)
