"""Track T4. Classifies a failed step's error output into the four failure classes."""

from __future__ import annotations

import hashlib
import os
import re

import httpx
from firstrun import tracing

from firstrun import config
from firstrun.models import Classification, FailureClass

JEV_URL = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = "jev-latest"

# Usage of the last Claude fallback call. recovery.py adds it to the run, then clears it.
LAST_USAGE: dict = {}

_TELLING = re.compile(
    r"error|exception|not found|failed|denied|no matching|cannot|can't|unable|unauthorized|refused|timed out|invalid|unknown|unrecognized",
    re.I,
)


def signature(error_text: str) -> str:
    """Short stable signature of an error: strips paths, numbers and hashes."""
    lines = [ln.strip() for ln in error_text.splitlines() if ln.strip()]
    telling = [ln for ln in lines if _TELLING.search(ln)]
    line = (telling or lines or [""])[-1]  # tools print the real error last
    line = line.lower()
    line = re.sub(r"[\"'`]", "", line)
    line = re.sub(r"(?:[a-z]:)?[\\/][^\s:,;)]*", "<path>", line)
    line = re.sub(r"\b(?:0x)?[0-9a-f]{7,}\b", "<hex>", line)
    line = re.sub(r"\d+(?:\.\d+)*", "<n>", line)
    line = re.sub(r"\s+", " ", line).strip()
    digest = hashlib.sha1(line.encode("utf-8")).hexdigest()[:12]
    prefix = re.sub(r"[^a-z]+", "-", line).strip("-")[:30].strip("-")
    return f"{prefix}-{digest}" if prefix else digest


def _normalize(raw: dict) -> dict[FailureClass, float]:
    probs = {c: max(0.0, float(raw.get(c.value, 0.0) or 0.0)) for c in FailureClass}
    total = sum(probs.values())
    if total <= 0:
        raise ValueError("no probabilities")
    return {c: p / total for c, p in probs.items()}


_CRITERIA = {
    "docs_bug": "The docs are wrong: package renamed, flag removed, wrong import path, or a version that moved.",
    "environment": "The sandbox is missing something: a system package in the base image, or a network timeout.",
    "product_bug": "The tool itself crashes on a correct command.",
    "needs_secret": "The step asks for an API key, token or login that the container lacks.",
}


def _jev(error_text: str, command: str) -> dict[FailureClass, float] | None:
    """Ask Jev one Choice question. Returns None on any failure."""
    config.load_env()
    key = os.environ.get("TYPESAFE_API_KEY")
    if not key:
        return None
    body = {
        "model": JEV_MODEL,
        "state": {"command": command, "error_output": error_text[-3000:]},
        "questions": {"failure_class": {
            "type": "choice",
            "instructions": "A shell command from a quickstart guide failed in a clean container. Which kind of failure is it?",
            "criteria": _CRITERIA,
        }},
    }
    try:
        r = httpx.post(JEV_URL, json=body, headers={"Authorization": f"Bearer {key}"}, timeout=30)
        r.raise_for_status()
        answer = r.json()["answers"]["failure_class"]
        return _normalize(answer["probabilities"])
    except Exception:  # any failure sends us to the next fallback
        return None


def _claude(error_text: str, command: str) -> dict[FailureClass, float] | None:
    from firstrun import llm

    prompt = (
        "A shell command from a developer quickstart failed in a clean Docker container.\n"
        f"Command: {command}\nError output:\n{error_text[-3000:]}\n\n"
        "Classes: " + "; ".join(f"{k}: {v}" for k, v in _CRITERIA.items()) + "\n"
        'Return JSON: {"docs_bug": p, "environment": p, "product_bug": p, "needs_secret": p} '
        "with probabilities that sum to 1."
    )
    try:
        data, usage = llm.ask_json(prompt, system="You classify failures.", max_turns=1)
        LAST_USAGE.clear()
        LAST_USAGE.update(usage)
        return _normalize(data)
    except Exception:
        return None


# Ordered: the first matching group wins.
_HEURISTICS: list[tuple[FailureClass, re.Pattern]] = [
    (FailureClass.NEEDS_SECRET, re.compile(
        r"api[_ -]?key|auth(?:entication|orization)? (?:required|failed|error)|unauthorized|\b401\b|"
        r"not logged in|please log ?in|missing (?:token|credentials)|invalid (?:token|credentials)|(?-i:[A-Z][A-Z0-9_]+_(?:KEY|TOKEN|SECRET)\b)", re.I)),
    (FailureClass.ENVIRONMENT, re.compile(
        r"command not found|: not found|no such file or directory: '?(?:gcc|cc|make|git|curl)|"
        r"could not resolve host|temporary failure in name resolution|timed out|connection (?:refused|reset)|"
        r"failed to build wheel|error: command '(?:gcc|cc)' failed|python\.h|unable to locate package", re.I)),
    (FailureClass.DOCS_BUG, re.compile(
        r"no matching distribution|could not find a version|modulenotfounderror|importerror|cannot import name|"
        r"unrecognized arguments|no such option|unknown (?:option|command|flag)|unexpected keyword|"
        r"has no attribute|is not a known|deprecated|removed|404|no such command|invalid choice", re.I)),
    (FailureClass.PRODUCT_BUG, re.compile(
        r"segmentation fault|internal (?:server )?error|panic:|assertionerror|unhandled exception|core dumped|\b500\b", re.I)),
]


def _heuristic(error_text: str, command: str = "") -> dict[FailureClass, float]:
    for cls, pattern in _HEURISTICS:
        if pattern.search(error_text):
            rest = 0.2 / 3
            return {c: (0.8 if c == cls else rest) for c in FailureClass}
    return {c: 0.25 for c in FailureClass}  # no signal: low confidence, so we ask


@tracing.span(kind="TOOL", name="classify_failure")
def classify(error_text: str, command: str = "") -> Classification:
    """TOOL span `classify_failure`. Jev first, Claude as fallback. Returns four probabilities."""
    config.assert_model_call_allowed("classification")
    probs = _jev(error_text, command)
    if probs is not None:
        return Classification(probabilities=probs, source="jev")
    tracing.log("jev unavailable, falling back to claude", level="warning")
    probs = _claude(error_text, command)
    if probs is not None:
        return Classification(probabilities=probs, source="claude")
    tracing.log("claude unavailable, falling back to heuristics", level="warning")
    return Classification(probabilities=_heuristic(error_text, command), source="heuristic")
