"""Langfuse setup, and the one tracing API the rest of 1stRun calls. Every 1stRun run is one trace.

No other module imports langfuse. They call `trace`, `span`, `log`, `annotate`, `set_io` and `mark_error` from here,
so the backend can change in this file alone. With no keys, or with ONESTRUN_NO_EXPORT=1, every call is a no-op.
"""

from __future__ import annotations

import contextlib
import functools
import inspect
import json
import os
import sys
from typing import Any, Callable

from onestrun.config import load_env

# 1stRun's span kinds, mapped to Langfuse observation types.
_KINDS = {
    "WORKFLOW": "chain", "AGENT": "agent", "TOOL": "tool", "GUARDRAIL": "guardrail", "LLM": "generation",
    "SPAN": "span",
}
_LEVELS = {"debug": "DEBUG", "info": "DEFAULT", "warning": "WARNING", "warn": "WARNING", "error": "ERROR",
           "critical": "ERROR"}

_ready = False
_client: Any = None  # the Langfuse client, or None while tracing is off
_tags: list[str] = []


def enabled() -> bool:
    """True when spans leave this process."""
    return _client is not None


def init_tracing(tags: list[str] | None = None, *, disable_export: bool | None = None) -> None:
    """Start Langfuse once per process. Tests set ONESTRUN_NO_EXPORT=1 to keep tracing off."""
    global _ready, _client, _tags
    if _ready:
        return
    load_env()
    _tags = list(tags or [])
    keys = bool(os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"))
    if disable_export is None:
        disable_export = os.environ.get("ONESTRUN_NO_EXPORT") == "1" or not keys
    if not keys and os.environ.get("ONESTRUN_NO_EXPORT") != "1":
        print("warning: LANGFUSE_PUBLIC_KEY or LANGFUSE_SECRET_KEY is missing. The run works, but no trace is exported.",
              file=sys.stderr)
    _ready = True
    if disable_export:
        return
    try:
        from langfuse import Langfuse

        _client = Langfuse(debug=os.environ.get("ONESTRUN_DEBUG") == "1")
        _instrument_claude_sdk()
    except Exception as exc:  # noqa: BLE001 - tracing is best effort, a run never fails because of it
        _client = None
        print(f"warning: Langfuse did not start ({str(exc)[:120]}). The run works, but no trace is exported.",
              file=sys.stderr)


def _instrument_claude_sdk() -> None:
    """Every Claude Agent SDK query becomes a generation under the span that is open when it runs."""
    try:
        from openinference.instrumentation.claude_agent_sdk import ClaudeAgentSDKInstrumentor
        from opentelemetry import trace as otel_trace

        ClaudeAgentSDKInstrumentor().instrument(tracer_provider=otel_trace.get_tracer_provider())
    except Exception:  # noqa: BLE001 - the plain SDK still works
        pass


def close_tracing() -> None:
    """Send buffered spans. No shutdown here: it blocks on ingestion, and the SDK's atexit hook closes it."""
    if _client is None:
        return
    try:
        _client.flush()
    except Exception:  # noqa: BLE001
        pass


def shutdown_tracing() -> None:
    if _client is None:
        return
    try:
        _client.shutdown()
    except Exception:  # noqa: BLE001
        pass


def _plain(value: Any) -> Any:
    """A JSON-safe copy of value. Anything JSON cannot hold becomes its string."""
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except Exception:  # noqa: BLE001
        return str(value)


def _json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        return str(value)


def session_attrs(target: str, command: str, **meta) -> dict:
    """Session and end-user fields: every trace about one docs site lands in one session,
    and the docs site is the end user, so a dashboard can filter by site."""
    return {"session_id": f"docs:{target}", "end_user_id": target,
            "end_user_metadata": {"command": command, **{k: v for k, v in meta.items() if v not in (None, "")}}}


class Span:
    """What `trace` yields. Never raises, and does nothing while tracing is off."""

    def __init__(self, obs: Any = None):
        self._obs = obs

    def update(self, **fields) -> None:
        if self._obs is None:
            return
        try:
            self._obs.update(**fields)
        except Exception:  # noqa: BLE001
            pass

    def set_attribute(self, key: str, value: Any) -> None:
        self.update(metadata={key: _plain(value)})


def set_io(span, input=None, output=None) -> None:
    """Record safe input and output on a span opened with `trace`. Never raises."""
    fields = {}
    if input is not None:
        fields["input"] = _plain(input)
    if output is not None:
        fields["output"] = _plain(output)
    if fields and hasattr(span, "update"):
        span.update(**fields)


def mark_error(span, message: str) -> None:
    """Set ERROR level on a span for a failure the app handled itself. Never raises."""
    if hasattr(span, "update"):
        span.update(level="ERROR", status_message=message[:300])


@contextlib.contextmanager
def trace(name: str, kind: str = "SPAN", **attrs):
    """Open a span named `name` and make it the current one. `attrs` become metadata, except these:
    session_id, end_user_id and end_user_metadata set the session and user for the whole trace, and tags tags it."""
    if _client is None:
        yield Span()
        return
    session_id = attrs.pop("session_id", None)
    user_id = attrs.pop("end_user_id", None)
    user_meta = attrs.pop("end_user_metadata", None)
    tags = [str(t)[:200] for t in [*_tags, *(attrs.pop("tags", None) or [])]]
    prop: dict[str, Any] = {}
    if session_id:
        prop["session_id"] = str(session_id)[:200]
    if user_id:
        prop["user_id"] = str(user_id)[:200]
    if user_meta:
        prop["metadata"] = {str(k): str(v)[:200] for k, v in user_meta.items()}
    if tags:
        prop["tags"] = list(dict.fromkeys(tags))
    with contextlib.ExitStack() as stack:
        try:
            from langfuse import propagate_attributes

            if prop:
                stack.enter_context(propagate_attributes(**prop))
            obs = stack.enter_context(_client.start_as_current_observation(
                name=name, as_type=_KINDS.get(kind.upper(), "span"), metadata=_plain(attrs) or None))
        except Exception:  # noqa: BLE001 - a tracing failure never stops the run
            obs = None
        yield Span(obs)


def span(kind: str = "SPAN", name: str | None = None) -> Callable:
    """Decorator form of `trace`. Records the call's arguments as input and its return value as output."""

    def deco(fn: Callable) -> Callable:
        label = name or fn.__name__
        sig = inspect.signature(fn)

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if _client is None:
                return fn(*args, **kwargs)
            with trace(label, kind=kind) as sp:
                try:
                    bound = sig.bind_partial(*args, **kwargs)
                    set_io(sp, input={k: _json(v)[:2000] for k, v in bound.arguments.items()})
                except Exception:  # noqa: BLE001
                    pass
                out = fn(*args, **kwargs)
                set_io(sp, output=_json(out)[:4000])
                return out

        return wrapper

    return deco


def log(message: str, level: str = "info", **fields) -> None:
    """Record one event on the current span. `{name}` in message fills from fields."""
    if _client is None:
        return
    try:
        text = message.format(**fields)
    except Exception:  # noqa: BLE001
        text = message
    try:
        _client.create_event(name=text[:200], level=_LEVELS.get(level.lower(), "DEFAULT"), status_message=text,
                             metadata=_plain(fields) or None)
    except Exception:  # noqa: BLE001
        pass


def annotate(**fields) -> None:
    """Add metadata to the span that is open now. Never raises."""
    if _client is None:
        return
    try:
        _client.update_current_span(metadata=_plain(fields))
    except Exception:  # noqa: BLE001
        pass


@span(kind="WORKFLOW", name="onestrun.hello")
def hello(name: str = "1stRun") -> str:
    log("hello from {name}", name=name)
    return f"hello, {name}"


if __name__ == "__main__":
    init_tracing(tags=["hello"], disable_export=False)
    print(hello())
    close_tracing()
    shutdown_tracing()
