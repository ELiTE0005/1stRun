"""Track T4. Classify, search, patch, retry. At most 3 attempts per step."""

from __future__ import annotations

import re
import sys
import threading
from typing import Callable

import httpx
from onestrun import tracing

from onestrun import budget as budget_mod
from onestrun import classify as classify_mod
from onestrun import config, llm, precedents
from onestrun.tracing import mark_error, set_io
from onestrun.budget import BudgetExceeded
from onestrun.models import (
    Budget,
    Classification,
    FailureClass,
    GaveUp,
    Patch,
    RunState,
    Step,
    StepResult,
)

CONFIDENT = 0.7        # below this, ask the human once
STORE_CONFIDENT = 0.9  # at or above this, a model answer is stored as a precedent

_LETTERS = {"d": FailureClass.DOCS_BUG, "e": FailureClass.ENVIRONMENT,
            "p": FailureClass.PRODUCT_BUG, "s": FailureClass.NEEDS_SECRET}

Asker = Callable[[str], str]

ASK_TIMEOUT_S = 60  # the human has this long to answer the ask-once question


class AskTimeout(Exception):
    """A person sat at the terminal and gave no answer within ASK_TIMEOUT_S seconds."""


class NeedsHuman(Exception):
    """The human gave no answer. `classification` holds the model's best guess."""

    def __init__(self, classification: Classification):
        super().__init__("needs_human: no answer to the ask-once question")
        self.classification = classification


def _error_line(error_text: str) -> str:
    lines = [ln.strip() for ln in error_text.splitlines() if ln.strip()]
    return (lines[-1] if lines else "no output")[:200]


def _terminal_asker(question: str) -> str | None:
    """Ask in the terminal. No terminal returns None. No answer in ASK_TIMEOUT_S seconds raises AskTimeout."""
    if not sys.stdin or not sys.stdin.isatty():
        return None
    box: list[str | None] = []

    def read() -> None:
        try:
            box.append(input(question + " "))
        except (EOFError, OSError):  # a console with no reader, such as a background job
            box.append(None)

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    reader.join(ASK_TIMEOUT_S)
    if not box:
        raise AskTimeout(f"no answer in {ASK_TIMEOUT_S} s")
    return box[0]


def _parse_answer(answer: str | None) -> FailureClass | None:
    if not answer:
        return None
    a = answer.strip().lower()
    for cls in FailureClass:
        if a == cls.value or a == cls.value.replace("_", " "):
            return cls
    return _LETTERS.get(a[:1]) if len(a) == 1 else None


def _resolve(error_text: str, command: str, asker: Asker | None, step_id: int | None) -> Classification:
    sig = classify_mod.signature(error_text)
    known = precedents.lookup(sig)
    if known is not None:
        tracing.log("precedent reused", signature=sig, failure_class=known.value)
        return Classification(probabilities={c: (1.0 if c == known else 0.0) for c in FailureClass},
                              source="precedent")
    if _NETWORK.search(error_text):  # a dropped network is the environment, whatever a model says
        return Classification(probabilities={c: (1.0 if c == FailureClass.ENVIRONMENT else 0.0) for c in FailureClass},
                              source="rule")
    cls = classify_mod.classify(error_text, command)
    if round(cls.confidence, 6) >= CONFIDENT:
        if cls.confidence >= STORE_CONFIDENT:
            precedents.store(sig, cls.top, example=error_text)
        return cls
    where = f"Step {step_id}" if step_id is not None else "Step"
    question = (f"{where} failed: {_error_line(error_text)}. Is this a docs bug, an environment issue, "
                "a product bug, or a missing secret? [d/e/p/s]")
    ask = asker or _terminal_asker
    try:
        answer = _parse_answer(ask(question))
    except AskTimeout:
        tracing.log("no human answer within {secs} s: step needs a human", level="warning",
                     secs=ASK_TIMEOUT_S, failure_class=cls.top.value, confidence=cls.confidence)
        raise NeedsHuman(cls)
    if answer is None:  # no terminal to ask: use the top class
        tracing.log("no human answer, using the top class", level="warning",
                     failure_class=cls.top.value, confidence=cls.confidence)
        return cls
    precedents.store(sig, answer, example=error_text)
    return Classification(probabilities={c: (1.0 if c == answer else 0.0) for c in FailureClass},
                          source="human")


def resolve_class(error_text: str, command: str, asker: Asker | None = None,
                  step_id: int | None = None) -> tuple[FailureClass, str]:
    """Precedent first, then the classifier, then ask the human once if unsure."""
    try:
        cls = _resolve(error_text, command, asker, step_id)
    except NeedsHuman as exc:
        return exc.classification.top, "unanswered"
    return cls.top, cls.source


_NETWORK = re.compile(
    r"temporary failure in name resolution|could not resolve host|name or service not known|network is unreachable|"
    r"connection (?:reset|aborted)|connectionerror|max retries exceeded|read timed out|failed to establish a new connection|"
    r"connection timed out|tls handshake timeout", re.I)

# --- environment fixes -------------------------------------------------------

# (error pattern, apt packages). A small known table so most fixes need no model.
_ENV_FIXES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bcurl: (?:command )?not found|curl: not found|\bcurl\b.*not found", re.I), "curl"),
    (re.compile(r"\bgit: (?:command )?not found|\bgit\b.*not found|No such file or directory: 'git'", re.I), "git"),
    (re.compile(r"\bwget: (?:command )?not found|\bwget\b.*not found", re.I), "wget"),
    (re.compile(r"\b(?:gcc|cc|g\+\+|make): (?:command )?not found|command 'gcc' failed|unable to execute 'gcc'|"
                r"failed to build wheel|python\.h: no such file", re.I), "build-essential"),
    (re.compile(r"\b(?:node|npm|npx): (?:command )?not found", re.I), "nodejs npm"),
]


def _env_packages(error_text: str) -> str | None:
    for pattern, pkgs in _ENV_FIXES:
        if pattern.search(error_text):
            return pkgs
    return None


# --- docs bug hints ----------------------------------------------------------

_PIP_MISSING = re.compile(r"No matching distribution found for ([A-Za-z0-9_.\-]+)(?:\[[^\]]*\])?\s*(?:==|>=|<=|~=|>|<)?\s*([\w.]*)")


def _pypi_hint(error_text: str) -> str:
    """Cheap first hint with no model: valid versions of the package pip could not find."""
    m = _PIP_MISSING.search(error_text)
    if not m:
        return ""
    name = m.group(1)
    try:
        r = httpx.get(f"https://pypi.org/pypi/{name}/json", timeout=10)
        if r.status_code == 404:
            return f"PyPI hint: no package named {name} exists on PyPI. It may have been renamed."
        r.raise_for_status()
        releases = [v for v, files in r.json().get("releases", {}).items() if files and not all(f.get("yanked") for f in files)]
        try:
            from packaging.version import Version
            releases.sort(key=Version)
        except Exception:
            pass
        latest = r.json().get("info", {}).get("version", "")
        return f"PyPI hint: {name} has these versions (newest last): {', '.join(releases[-15:])}. Latest is {latest}."
    except Exception:
        return ""


def _read_allowlist() -> dict[str, str]:
    """KEY=VALUE lines. Values are never logged or returned to callers outside this module."""
    out: dict[str, str] = {}
    try:
        for line in config.SECRETS_ALLOWLIST.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


def _add_usage(state: RunState, usage: dict) -> None:
    state.usage.tool_calls += int(usage.get("tool_calls", 0))
    state.usage.input_tokens += int(usage.get("input_tokens", 0))
    state.usage.output_tokens += int(usage.get("output_tokens", 0))
    state.usage.cost_usd += float(usage.get("cost_usd", 0.0))


_APT = re.compile(r"\b(apt-get|apt|apk|yum|dnf) (-\S+ )*install\b")

_NOISE = re.compile(
    r"^\s*(\[notice\]|Requirement already satisfied|Collecting |Downloading |Using cached |Installing collected"
    r"|Successfully (installed|uninstalled)|Uninstalling |Attempting uninstall|Found existing installation"
    r"|Building wheel|Created wheel|Stored in directory|Preparing metadata|Getting requirements|Installing build)"
)


def _clean(text: str) -> str:
    """Drop package-manager progress lines, so the real error is what the classifier reads."""
    return "\n".join(ln for ln in text.splitlines() if ln.strip() and not _NOISE.match(ln))


def _error_text(result: StepResult) -> str:
    """stdout first and stderr last, noise removed, so the tail holds the real error."""
    out, err = _clean(result.stdout or "")[-800:], _clean(result.stderr or "")[-2200:]
    text = out + ("\n" if out and err else "") + err
    if result.timed_out:
        text += "\n(command timed out)"
    return text[-3000:]


def _search_terms(step: Step, old_command: str, error_text: str) -> str:
    return f"{old_command.split()[0] if old_command.split() else ''} {step.intent} | {_error_line(error_text)}"[:200]


def _short_reason(text: str, limit: int = 400) -> str:
    """Keep whole sentences up to the limit, so a PR body never ends mid-word."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text.rfind(". ", 0, limit)
    return text[: cut + 1] if cut > 0 else text[:limit].rsplit(" ", 1)[0] + "."


def _intent_tokens(command: str) -> set[str]:
    """Program names and non-flag args of each `&&` part, ignoring sudo and a leading `cd X &&`."""
    parts = [p.strip() for p in re.split(r"&&|\|\||;|\|", command) if p.strip()]
    if parts and re.match(r"cd\s+\S+$", parts[0]) and len(parts) > 1:
        parts = parts[1:]
    out: set[str] = set()
    for part in parts:
        for tok in part.split():
            if tok != "sudo" and not tok.startswith("-"):
                out.add(tok.strip("\"'"))
    return out


def drifted(old_command: str, new_command: str) -> bool:
    """True when fewer than 60% of the original command's main tokens survive in the new one."""
    want = _intent_tokens(old_command)
    if not want:
        return False
    have = _intent_tokens(new_command)
    return len(want & have) / len(want) < 0.6


def _ask_fix(prompt: str, tools: tuple[str, ...], max_turns: int, state: RunState, bud: Budget,
             step: Step, old_command: str, cls: FailureClass, tried: list[str],
             error_text: str = "") -> Patch | GaveUp:
    """One budgeted Claude call that must return {new_command, reason, source}."""
    try:
        budget_mod.check(state, bud, step.id)
    except BudgetExceeded as exc:
        return GaveUp(step_id=step.id, reason=str(exc), failure_class=cls)
    try:
        data, usage = llm.ask_json(prompt, system="You fix failing shell commands from developer quickstart guides.",
                                   tools=tools, max_turns=max_turns)
    except Exception as exc:  # noqa: BLE001
        why = "model auth failed" if isinstance(exc, llm.ModelAuthError) else f"model call failed: {type(exc).__name__}"
        return GaveUp(step_id=step.id, reason=why, failure_class=cls)
    _add_usage(state, usage)
    new = str(data.get("new_command") or "").strip()
    if not new or new == old_command.strip() or new in tried:
        terms = _search_terms(step, old_command, error_text)
        tracing.log("fix search found nothing: {terms}", level="warning", terms=terms, step_id=step.id)
        return GaveUp(step_id=step.id, failure_class=cls,
                      reason=f"no new fix found (searched: {terms})")
    if drifted(old_command, new):
        tracing.log("patch rejected: drift", level="warning", step_id=step.id, old=old_command, new=new)
        return GaveUp(step_id=step.id, failure_class=cls,
                      reason=f"fix drifted from the docs command: `{new[:120]}`")
    # A fix that only installs system packages before the original command is a container fix.
    if cls == FailureClass.DOCS_BUG and _APT.search(new) and old_command.strip() in new:
        cls = FailureClass.ENVIRONMENT
    return Patch(step_id=step.id, old_command=old_command, new_command=new,
                 reason=_short_reason(str(data.get("reason") or "")), failure_class=cls,
                 source=str(data.get("source") or ""))


def recover(step: Step, result: StepResult, state: RunState, docs_markdown: str = "",
            asker: Asker | None = None, budget: Budget | None = None) -> Patch | GaveUp:
    """AGENT span `recover.<id>`. Returns a Patch to retry with, or GaveUp."""
    bud = budget or Budget()
    with tracing.trace(f"recover.{step.id}", kind="AGENT") as span:
        set_io(span, input={"step_id": step.id, "command": result.command or step.command,
                            "exit_code": result.exit_code, "error": _error_line(_error_text(result))})
        outcome = _recover(step, result, state, docs_markdown, asker, bud)
        if isinstance(outcome, Patch):
            set_io(span, output={"patch": outcome.new_command, "reason": outcome.reason,
                                 "failure_class": outcome.failure_class.value, "source": outcome.source})
        else:
            set_io(span, output={"gave_up": outcome.reason,
                                 "failure_class": outcome.failure_class.value if outcome.failure_class else None})
            mark_error(span, f"gave up on step {step.id}: {outcome.reason}")
        return outcome


def _recover(step: Step, result: StepResult, state: RunState, docs_markdown: str,
             asker: Asker | None, bud: Budget) -> Patch | GaveUp:
    error_text = _error_text(result)
    old_command = result.command or step.command
    attempts = state.attempts.get(step.id, 0)
    tracing.log("retry {attempt} after {error}", level="warning",
                 attempt=max(attempts, 1), error=_error_line(error_text))
    try:
        budget_mod.check(state, bud, step.id)
    except BudgetExceeded as exc:
        return GaveUp(step_id=step.id, reason=str(exc))

    classify_mod.LAST_USAGE.clear()
    if result.timed_out:  # a hung step is an environment failure and a retry would hang again
        cls = Classification(probabilities={c: (1.0 if c == FailureClass.ENVIRONMENT else 0.0) for c in FailureClass},
                             source="timeout")
        state.classifications[step.id] = cls
        return GaveUp(step_id=step.id, reason=f"step timed out after {bud.seconds_per_step} s: {_error_line(error_text)}",
                      failure_class=FailureClass.ENVIRONMENT)
    try:
        cls = _resolve(error_text, old_command, asker, step.id)
    except NeedsHuman as exc:
        state.classifications[step.id] = exc.classification
        return GaveUp(step_id=step.id, failure_class=exc.classification.top,
                      reason=f"needs_human: no answer within {ASK_TIMEOUT_S} s to the ask-once question")
    if classify_mod.LAST_USAGE:  # the classifier fell back to Claude
        _add_usage(state, classify_mod.LAST_USAGE)
        classify_mod.LAST_USAGE.clear()
    state.classifications[step.id] = cls
    top = cls.top

    tried = [p.new_command for p in state.patches if p.step_id == step.id]

    if top == FailureClass.PRODUCT_BUG:
        return GaveUp(step_id=step.id, reason=f"product bug: {_error_line(error_text)}", failure_class=top)

    if top == FailureClass.NEEDS_SECRET:
        allow = _read_allowlist()
        haystack = f"{error_text}\n{old_command}\n{docs_markdown}"
        name = next((k for k in allow if re.search(rf"\b{re.escape(k)}\b", haystack)), None)
        if name is None:
            return GaveUp(step_id=step.id, reason="needs a secret that is not in the allowlist: "
                          + _error_line(error_text), failure_class=top)
        # The container already had this key from the allowlist, so a retry would fail the same way.
        return GaveUp(step_id=step.id, failure_class=top,
                      reason=f"{name} is set from the allowlist but the step still fails, so the key is "
                             f"likely invalid or lacks access: " + _error_line(error_text))

    if top == FailureClass.ENVIRONMENT:
        if _NETWORK.search(error_text):  # a dropped network: retry the same command once
            retried = [p for p in state.patches if p.step_id == step.id and p.source == "retry"]
            if retried:
                return GaveUp(step_id=step.id, failure_class=top,
                              reason=f"network error again after one retry: {_error_line(error_text)}")
            return Patch(step_id=step.id, old_command=old_command, new_command=old_command,
                         reason="network error; retry once", failure_class=top, source="retry")
        pkgs = _env_packages(error_text)
        if pkgs:
            new = f"apt-get update -qq && apt-get install -y -qq {pkgs} && {old_command}"
            if new not in tried:
                return Patch(step_id=step.id, old_command=old_command, new_command=new,
                             reason=f"the base image lacks {pkgs}; install it first", failure_class=top,
                             source="apt")
        prompt = (f"A command failed in a clean python:3.11-slim container because of the environment.\n"
                  f"Command: {old_command}\nError tail:\n{error_text}\n"
                  f"Earlier fixes that did not work: {tried or 'none'}\n"
                  'Return JSON {"new_command": "...", "reason": "...", "source": "..."}. '
                  "new_command must run the original command after any container fix, as one shell line."
                  " Keep the original command and its arguments. Only add a missing prerequisite or change a version, flag or name that the error proves wrong.")
        return _ask_fix(prompt, (), 1, state, bud, step, old_command, top, tried, error_text)

    # docs_bug
    hint = _pypi_hint(error_text)
    prompt = (f"A step from a developer quickstart failed in a clean Docker container (python:3.11-slim).\n"
              f"Step intent: {step.intent}\nCommand: {old_command}\nError tail:\n{error_text}\n"
              f"{hint}\n"
              f"Earlier patches for this step that also failed: {tried or 'none'}\n"
              f"Docs excerpt:\n{docs_markdown[:3000]}\n\n"
              "Find the current, correct command with WebSearch and WebFetch. Prefer the tool's own docs, "
              "its registry page or its issue tracker. "
              " Keep the original command and its arguments. Only add a missing prerequisite or change a version, flag or name that the error proves wrong. "
              'Return JSON {"new_command": "...", "reason": "...", "source": "<url you used>"}.')
    return _ask_fix(prompt, ("WebSearch", "WebFetch"), 6, state, bud, step, old_command, top, tried, error_text)
