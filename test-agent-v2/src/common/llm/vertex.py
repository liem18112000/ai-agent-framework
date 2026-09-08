"""Claude-on-Vertex (AnthropicVertex) client helpers and env-driven config."""

from __future__ import annotations

import asyncio
import os
from typing import Any

_ENV_KEYS = ("VERTEX_PROJECT", "VERTEX_LOCATION", "VERTEX_MODEL")


def vertex_config() -> tuple[str, str, str] | None:
    """Return (project, location, model) from env, or None if any is unset."""
    proj, loc, model = (os.environ.get(k) for k in _ENV_KEYS)
    return (proj, loc, model) if (proj and loc and model) else None


def first_text(msg: Any) -> str:
    """Return the first text block from an Anthropic message, skipping non-text blocks."""
    for block in msg.content:
        if getattr(block, "type", None) == "text":
            return block.text
    return ""


def complete(prompt: str, *, project: str, location: str, model: str, max_tokens: int) -> str:
    """Run one Claude-on-Vertex completion and return its first text block."""
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
    """Non-blocking `complete()` — run the blocking Vertex call in a worker thread."""
    return await asyncio.to_thread(
        complete, prompt, project=project, location=location, model=model, max_tokens=max_tokens
    )
