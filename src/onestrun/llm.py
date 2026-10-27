"""Track T4. Small sync helpers over the Claude Agent SDK. Traced by the Langfuse instrumentor in tracing.py."""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
import threading
from typing import Any, Sequence

import claude_agent_sdk

from onestrun import config

# tracing.init_tracing patches claude_agent_sdk.query in place, so every query shows up in the trace.
sdk = claude_agent_sdk

# A cwd outside the repo, so project hooks and settings never fire.
_WORKDIR = os.path.join(tempfile.gettempdir(), "1stRun-llm")


class ModelAuthError(RuntimeError):
    """The Claude subscription token is missing, expired or rejected."""


_AUTH_HINTS = ("401", "authentication", "unauthorized", "invalid api key", "oauth token", "token has expired",
               "token expired", "please run /login", "not logged in", "setup-token")


def _looks_like_auth_error(text: str) -> bool:
    low = (text or "").lower()
    return any(h in low for h in _AUTH_HINTS)


def _cost(input_tokens: int, output_tokens: int, cache_write: int = 0, cache_read: int = 0) -> float:
    """List price, not billed. Cache writes cost 1.25x input, cache reads 0.1x input."""
    return (
        input_tokens * config.PRICE_INPUT_PER_MTOK
        + cache_write * config.PRICE_INPUT_PER_MTOK * 1.25
        + cache_read * config.PRICE_CACHE_READ_PER_MTOK
        + output_tokens * config.PRICE_OUTPUT_PER_MTOK
    ) / 1_000_000


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of a reply, with or without a code fence."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidates = [fence.group(1)] if fence else []
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])
    for c in candidates:
        try:
            value = json.loads(c)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("no JSON object in model reply")


async def _run(prompt: str, system: str, tools: Sequence[str], max_turns: int,
               model: str | None = None) -> tuple[str, dict]:
    config.load_env()
    os.makedirs(_WORKDIR, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "ANTHROPIC_API_KEY")}
    options = claude_agent_sdk.ClaudeAgentOptions(
        model=model or config.MODEL,
        effort=config.EFFORT,
        system_prompt=system,
        setting_sources=[],
        cwd=_WORKDIR,
        tools=list(tools),
        allowed_tools=list(tools),
        max_turns=max_turns,
        env=env,
    )
    text, tool_calls, usage = "", 0, {}
    try:
        async for msg in sdk.query(prompt=prompt, options=options):
            text, tool_calls, usage = _consume(msg, text, tool_calls, usage)
    except (config.ModelCallBlocked, ModelAuthError):
        raise
    except Exception as exc:  # noqa: BLE001
        if _looks_like_auth_error(str(exc)):
            raise ModelAuthError(f"model auth failed: {str(exc)[:200]}") from exc
        raise
    fresh = int(usage.get("input_tokens", 0) or 0)
    write = int(usage.get("cache_creation_input_tokens", 0) or 0)
    read = int(usage.get("cache_read_input_tokens", 0) or 0)
    tout = int(usage.get("output_tokens", 0) or 0)
    return text, {"input_tokens": fresh + write + read, "output_tokens": tout, "tool_calls": tool_calls,
                  "cost_usd": _cost(fresh, tout, write, read)}


def _consume(msg, text: str, tool_calls: int, usage: dict):
    if isinstance(msg, claude_agent_sdk.AssistantMessage):
        for block in msg.content:
            if isinstance(block, claude_agent_sdk.ToolUseBlock):
                tool_calls += 1
            elif isinstance(block, claude_agent_sdk.TextBlock):
                text = block.text  # the last text block is the answer
    elif isinstance(msg, claude_agent_sdk.ResultMessage):
        usage = msg.usage or {}
        if msg.is_error and not text:
            detail = f"{msg.result or msg.subtype}"
            if _looks_like_auth_error(detail):
                raise ModelAuthError(f"model auth failed: {detail[:200]}")
            raise RuntimeError(f"claude query failed: {detail}")
        if msg.result:
            text = msg.result
    return text, tool_calls, usage


def _run_sync(prompt: str, system: str, tools: Sequence[str], max_turns: int,
              model: str | None = None) -> tuple[str, dict]:
    config.assert_model_call_allowed("claude call")
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_run(prompt, system, tools, max_turns, model))
    # Already inside an event loop: run in a worker thread.
    box: dict[str, Any] = {}

    def work() -> None:
        try:
            box["out"] = asyncio.run(_run(prompt, system, tools, max_turns, model))
        except BaseException as exc:  # noqa: BLE001
            box["err"] = exc

    t = threading.Thread(target=work)
    t.start()
    t.join()
    if "err" in box:
        raise box["err"]
    return box["out"]


def ask(prompt: str, system: str = "", tools: Sequence[str] = (), max_turns: int = 1,
        model: str | None = None) -> tuple[str, dict]:
    """Plain text reply plus a usage dict. `model` overrides config.MODEL."""
    return _run_sync(prompt, system, tools, max_turns, model)


def ask_json(prompt: str, system: str = "", tools: Sequence[str] = (), max_turns: int = 1,
             model: str | None = None) -> tuple[dict, dict]:
    """JSON reply plus a usage dict {input_tokens, output_tokens, tool_calls, cost_usd}."""
    system = (system + "\n\n" if system else "") + "Reply with one JSON object and nothing else."
    text, usage = _run_sync(prompt, system, tools, max_turns, model)
    return extract_json(text), usage
