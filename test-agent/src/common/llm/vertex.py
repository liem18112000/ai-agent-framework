"""Claude-on-Vertex (AnthropicVertex) client helpers and env-driven config.

The single place that talks to the Anthropic SDK. Every LLM call in the package goes
through `complete()` (sync) or `agenerate()` (async, non-blocking off the event loop);
env resolution goes through `vertex_config()`.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

_ENV_KEYS = ("VERTEX_PROJECT", "VERTEX_LOCATION", "VERTEX_MODEL")


def vertex_config() -> tuple[str, str, str] | None:
    """Return (project, location, model) from env, or None if any is unset.

    A single None result is the "no LLM configured — use the heuristic fallback" signal
    the selection factories key off.
    """
    proj, loc, model = (os.environ.get(k) for k in _ENV_KEYS)
    return (proj, loc, model) if (proj and loc and model) else None


def first_text(msg: Any) -> str:
    """Return the first text block from an Anthropic message, skipping non-text blocks.

    Claude 4.5+/5 models (e.g. claude-sonnet-5) emit thinking blocks, so `msg.content[0]`
    can be a ThinkingBlock — which carries `.thinking`, not `.text`. Reading `.text` off it
    raises AttributeError. Walk the blocks and return the first text one instead of assuming
    position 0 is text.
    """
    for block in msg.content:
        if getattr(block, "type", None) == "text":
            return block.text
    return ""


def complete(prompt: str, *, project: str, location: str, model: str, max_tokens: int) -> str:
    """Run one Claude-on-Vertex completion and return its first text block.

    Thinking is disabled so the whole `max_tokens` budget goes to the answer: Claude 4.5+/5
    models think by default, which (a) makes the first content block a ThinkingBlock and
    (b) spends budget on thinking that would truncate these tight-budget outputs.

    Blocking (synchronous SDK call). Async A2A handlers must NOT call this directly on the
    event loop — go through `agenerate()`, or offload the calling subtree with
    `asyncio.to_thread`. A tens-of-seconds blocking call stalls the loop, so Cloud Run's
    /livez probe starves and the instance is killed mid-request with ERROR_TIMEOUT.
    """
    from anthropic import AnthropicVertex

    client = AnthropicVertex(project_id=project, region=location)
    msg = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        thinking={"type": "disabled"},
        messages=[{"role": "user", "content": prompt}],
    )
    return first_text(msg)


async def agenerate(prompt: str, *, project: str, location: str, model: str, max_tokens: int) -> str:
    """Non-blocking `complete()` — run the blocking Vertex call in a worker thread.

    The single async, non-blocking generate path for A2A handlers. It offloads the sync
    `complete()` with `asyncio.to_thread` rather than switching to `AsyncAnthropicVertex`
    so there stays exactly one code path through `complete()` — the symbol every `llm`
    module imports and every test monkeypatches — leaving the mock surface unchanged.
    """
    return await asyncio.to_thread(
        complete, prompt, project=project, location=location, model=model, max_tokens=max_tokens
    )
