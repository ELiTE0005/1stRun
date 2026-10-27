"""The judge: a model that classifies and scores small items for Doc-audit and as Doc-test's backup classifier.

Two backends answer the same questions:

- `claude`  Claude through the Agent SDK and your subscription token. Best quality. The default when a token is set.
- `local`   An OpenAI-compatible endpoint: a local Ollama (no key, no limits) or a free cloud tier.

    ONESTRUN_JUDGE                 off | claude | ollama. Unset: Claude if a token is set, else a local Ollama.
    ONESTRUN_JUDGE_CLAUDE_MODEL    a Claude model for the judge. Default: the model 1stRun uses elsewhere.
    ONESTRUN_JUDGE_BASE_URL        an OpenAI-compatible endpoint. Setting it picks the local backend.
    ONESTRUN_JUDGE_MODEL           that endpoint's model. Default qwen2.5:7b.
    ONESTRUN_JUDGE_API_KEY         only for a cloud endpoint.

A 7B local model was confidently wrong on public API changes, so it is a backup and not the audit's default.

`ask` takes a list of items and a few questions and answers each item once per question. It splits a long list into
calls that fit the backend's context, and a failed call leaves its items as None instead of raising. The one
exception is ModelCallBlocked: a verification run must never reach a model, so that error always passes through.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass

import httpx

from onestrun import config

DEFAULT_BASE_URL = "http://localhost:11434/v1"
DEFAULT_MODEL = "qwen2.5:7b"
CHUNK_CHARS = 5000  # item text per local call. About 1,300 tokens, so it fits Ollama's smallest default context.
CLAUDE_CHUNK_CHARS = 30000
MAX_ITEM_CHARS = 3500
COLD_START_S = 240
_OFF = ("off", "0", "false", "no")

USAGE = {"calls": 0, "input_tokens": 0, "cost_usd": 0.0}
_state: dict = {"checked": False, "ok": False, "last": ""}


@dataclass
class Choice:
    """Pick among named classes. The answer is a probability for each class."""
    instructions: str
    classes: dict[str, str]


@dataclass
class Score:
    """The answer is one probability between 0 and 1 that the statement is true."""
    instructions: str


def reset_usage() -> None:
    USAGE.update(calls=0, input_tokens=0, cost_usd=0.0)
    _state["last"] = ""


def base_url() -> str:
    return (os.environ.get("ONESTRUN_JUDGE_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")


def model() -> str:
    return os.environ.get("ONESTRUN_JUDGE_MODEL") or DEFAULT_MODEL


def claude_model() -> str | None:
    return os.environ.get("ONESTRUN_JUDGE_CLAUDE_MODEL") or None


def _headers() -> dict:
    key = os.environ.get("ONESTRUN_JUDGE_API_KEY")
    return {"Authorization": f"Bearer {key}"} if key else {}


def reset() -> None:
    """Forget the cached local check. Tests and a changed environment call this."""
    _state.update(checked=False, ok=False)


def claude_ready() -> bool:
    config.load_env()
    return bool(os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"))


def local_ready() -> bool:
    """True when the local endpoint can answer. Checked once per process.

    With ONESTRUN_JUDGE_BASE_URL set, 1stRun trusts it. Without it, 1stRun looks for a local Ollama
    that has the model pulled, and says so on stderr when Ollama runs without the model.
    """
    config.load_env()
    if os.environ.get("ONESTRUN_JUDGE_BASE_URL"):
        return True
    if _state["checked"]:
        return _state["ok"]
    _state["checked"] = True
    try:
        root = base_url().removesuffix("/v1")
        r = httpx.get(f"{root}/api/tags", timeout=1.5)
        r.raise_for_status()
        names = {m.get("name", "") for m in (r.json().get("models") or [])}
    except Exception:  # noqa: BLE001 - nothing listens: no local judge
        return False
    want = model()
    have = want in names or f"{want}:latest" in names or any(n.split(":")[0] == want for n in names if ":" not in want)
    if not have:
        print(f"warning: Ollama is running but the judge model is missing. Run: ollama pull {want}", file=sys.stderr)
        return False
    _state["ok"] = True
    return True


def backend(prefer: str | None = None) -> str | None:
    """The backend that answers now: "claude", "local" or None.

    `prefer` names one backend and ignores the other. Without it, ONESTRUN_JUDGE decides, then a configured
    endpoint, then Claude, then a local Ollama.
    """
    config.load_env()
    mode = os.environ.get("ONESTRUN_JUDGE", "").lower()
    if mode in _OFF:
        return None
    if prefer == "local":
        return "local" if local_ready() else None
    if prefer == "claude":
        return "claude" if claude_ready() else None
    if mode == "claude":
        return "claude" if claude_ready() else None
    if mode in ("ollama", "local"):
        return "local" if local_ready() else None
    if os.environ.get("ONESTRUN_JUDGE_BASE_URL"):
        return "local"
    if claude_ready():
        return "claude"
    return "local" if local_ready() else None


def available(prefer: str | None = None) -> bool:
    return backend(prefer) is not None


def describe() -> str:
    """One line for `1stRun doctor`."""
    b = backend()
    if b == "claude":
        return f"Claude ({claude_model() or config.MODEL}) through your subscription token"
    if b == "local":
        return f"{model()} at {base_url()}"
    return ""


def last_backend() -> str:
    """The backend that answered last in this process. Empty when none did."""
    return _state["last"]


def _extract(text: str) -> dict | None:
    """The first JSON object in a model reply."""
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    for candidate in (text, text[text.find("{"): text.rfind("}") + 1] if "{" in text else ""):
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _prompt(chunk: list[tuple[int, dict]], questions: dict) -> str:
    lines = ["Answer every question for every item. Judge only from the item text.", "", "Questions:"]
    shape: dict = {}
    for name, q in questions.items():
        if isinstance(q, Choice):
            lines.append(f'- "{name}": {q.instructions} Classes: ' + "; ".join(f"{k}: {v}" for k, v in q.classes.items()))
            shape[name] = {c: "p" for c in q.classes}
        else:
            lines.append(f'- "{name}": {q.instructions} Answer with one probability between 0 and 1.')
            shape[name] = "p"
    lines += ["", "Items:"]
    for i, item in chunk:
        lines.append(json.dumps({"id": i, **item}, ensure_ascii=False))
    lines += ["", "Reply with one JSON object only, in this shape. Each p is a probability. "
              "The class probabilities of one question add up to 1.",
              json.dumps({"results": [{"id": 0, **shape}]})]
    return "\n".join(lines)


def _clean(questions: dict, row: dict) -> dict | None:
    out = {}
    for name, q in questions.items():
        value = row.get(name)
        try:
            if isinstance(q, Choice):
                probs = {c: max(0.0, float(value.get(c, 0.0) or 0.0)) for c in q.classes}
                total = sum(probs.values())
                if total <= 0:
                    return None
                out[name] = {c: p / total for c, p in probs.items()}
            else:
                out[name] = min(1.0, max(0.0, float(value)))
        except (AttributeError, TypeError, ValueError):
            return None
    return out


def _rows(reply: dict | None, questions: dict) -> dict[int, dict]:
    rows = (reply or {}).get("results")
    if not isinstance(rows, list):
        return {}
    out = {}
    for row in rows:
        if isinstance(row, dict):
            cleaned = _clean(questions, row)
            try:
                out[int(row.get("id"))] = cleaned
            except (TypeError, ValueError):
                continue
    return {i: v for i, v in out.items() if v is not None}


def _call_local(chunk: list[tuple[int, dict]], questions: dict, timeout: float) -> dict[int, dict]:
    body = {
        "model": model(),
        "messages": [{"role": "system", "content": "You are a careful classifier. Reply with JSON only."},
                     {"role": "user", "content": _prompt(chunk, questions)}],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    url = f"{base_url()}/chat/completions"
    if not USAGE["calls"]:
        timeout = max(timeout, COLD_START_S)  # the first call of a process may wait while Ollama loads the model
    r = httpx.post(url, json=body, headers=_headers(), timeout=timeout)
    if r.status_code == 400:  # an endpoint without JSON mode: ask again without it
        body.pop("response_format")
        r = httpx.post(url, json=body, headers=_headers(), timeout=timeout)
    r.raise_for_status()
    data = r.json()
    USAGE["calls"] += 1
    USAGE["input_tokens"] += int((data.get("usage") or {}).get("prompt_tokens") or 0)
    _state["last"] = "local"
    return _rows(_extract(data["choices"][0]["message"]["content"]), questions)


def _call_claude(chunk: list[tuple[int, dict]], questions: dict, timeout: float) -> dict[int, dict]:
    from onestrun import llm

    data, usage = llm.ask_json(_prompt(chunk, questions), system="You are a careful classifier. Judge only from "
                               "the item text.", max_turns=1, model=claude_model())
    USAGE["calls"] += 1
    USAGE["input_tokens"] += int(usage.get("input_tokens") or 0)
    USAGE["cost_usd"] += float(usage.get("cost_usd") or 0.0)
    _state["last"] = "claude"
    return _rows(data, questions)


def _chunks(items: list[dict], budget: int) -> list[list[tuple[int, dict]]]:
    batches: list[list[tuple[int, dict]]] = []
    chunk: list[tuple[int, dict]] = []
    size = 0
    for i, item in enumerate(items):
        item = {k: (v[:MAX_ITEM_CHARS] if isinstance(v, str) else v) for k, v in item.items()}
        n = len(json.dumps(item, ensure_ascii=False))
        if chunk and size + n > budget:
            batches.append(chunk)
            chunk, size = [], 0
        chunk.append((i, item))
        size += n
    if chunk:
        batches.append(chunk)
    return batches


def ask(items: list[dict], questions: dict, timeout: float = 120, prefer: str | None = None) -> list[dict | None]:
    """One answer per item: {question name: {class: p}} for a Choice, {question name: p} for a Score, else None."""
    results: list[dict | None] = [None] * len(items)
    if not items or not questions:
        return results
    which = backend(prefer)
    if which is None:
        return results
    if which == "claude":
        budget = int(os.environ.get("ONESTRUN_JUDGE_CLAUDE_CHUNK_CHARS") or CLAUDE_CHUNK_CHARS)
        call = _call_claude
    else:
        budget = int(os.environ.get("ONESTRUN_JUDGE_CHUNK_CHARS") or CHUNK_CHARS)
        call = _call_local
    for batch in _chunks(items, budget):
        try:
            for i, answer in call(batch, questions, timeout).items():
                if 0 <= i < len(results):
                    results[i] = answer
        except config.ModelCallBlocked:
            raise
        except Exception:  # noqa: BLE001 - the judge is optional: these items stay unanswered
            continue
    return results
