"""neatlogs setup. Every FirstRun run is one trace."""

from __future__ import annotations

import os
import sys

import neatlogs

from firstrun.config import load_env

_ready = False


def init_tracing(tags: list[str] | None = None, *, disable_export: bool | None = None) -> None:
    """Start neatlogs once per process. Tests set FIRSTRUN_NO_EXPORT=1 to keep spans local."""
    global _ready
    if _ready:
        return
    load_env()
    if disable_export is None:
        disable_export = os.environ.get("FIRSTRUN_NO_EXPORT") == "1" or not os.environ.get("NEATLOGS_API_KEY")
    if not os.environ.get("NEATLOGS_API_KEY") and os.environ.get("FIRSTRUN_NO_EXPORT") != "1":
        print("warning: NEATLOGS_API_KEY is missing. The run works, but no trace is exported.", file=sys.stderr)
    neatlogs.init(
        api_key=os.environ.get("NEATLOGS_API_KEY"),
        workflow_name="firstrun",
        tags=tags or [],
        debug=os.environ.get("FIRSTRUN_DEBUG") == "1",
        capture_logs=True,
        disable_export=disable_export,
    )
    _ready = True


def close_tracing() -> None:
    """Drain buffered spans. No shutdown here: it blocks on ingestion, and the SDK's atexit hook closes it."""
    try:
        neatlogs.flush()
    except Exception:  # noqa: BLE001
        pass


def _json(value) -> str:
    import json

    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        return str(value)


def session_attrs(target: str, command: str, **meta) -> dict:
    """neatlogs session and end-user fields: every trace about one docs site lands in one session,
    and the docs site is the end user, so evals and alerts can filter by site."""
    return {"session_id": f"docs:{target}", "end_user_id": target,
            "end_user_metadata": {"command": command, **{k: v for k, v in meta.items() if v not in (None, "")}}}


def set_io(span, input=None, output=None) -> None:
    """Record safe input and output on a span opened with `neatlogs.trace`. Never raises."""
    try:
        if input is not None:
            span.set_attribute("input.value", _json(input))
            span.set_attribute("input.mime_type", "application/json")
        if output is not None:
            span.set_attribute("output.value", _json(output))
            span.set_attribute("output.mime_type", "application/json")
    except Exception:  # noqa: BLE001
        pass


def mark_error(span, message: str) -> None:
    """Set ERROR status on a span for a failure the app handled itself. Never raises."""
    try:
        from opentelemetry.trace import Status, StatusCode

        span.set_status(Status(StatusCode.ERROR, message[:300]))
    except Exception:  # noqa: BLE001
        pass


@neatlogs.span(kind="WORKFLOW", name="firstrun.hello")
def hello(name: str = "firstrun") -> str:
    neatlogs.log("hello from {name}", name=name)
    return f"hello, {name}"


if __name__ == "__main__":
    init_tracing(tags=["hello"], disable_export=False)
    print(hello())
    neatlogs.flush()
    neatlogs.shutdown()
