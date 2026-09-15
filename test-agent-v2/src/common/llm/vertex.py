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
    return next((b.text for b in msg.content if getattr(b, "type", None) == "text"), "")


def _user_content(prompt: str, cache_prefix: str | None):
    """The `messages` content: a plain string, or a [cached-prefix, prompt] block list when a
    stable `cache_prefix` is given (Anthropic prompt caching — cache_control: ephemeral)."""
    if not cache_prefix:
        return prompt
    return [
        {"type": "text", "text": cache_prefix, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": prompt},
    ]


def complete(prompt: str, *, project: str, location: str, model: str, max_tokens: int,
             cache_prefix: str | None = None, stream: bool = True) -> str:
    """Run one Claude-on-Vertex completion and return its first text block.

    Streams by default (`messages.stream`) — same result, but robust on long generations (keeps the
    connection alive past read timeouts). When `cache_prefix` is given, that stable block is
    **prompt-cached**, so repeated calls sharing it (e.g. the 4 define rounds over one pack) are
    materially faster and ~cheaper on the cached tokens; set `stream=False`/`cache_prefix=None` to opt out."""
    from anthropic import AnthropicVertex

    client = AnthropicVertex(project_id=project, region=location)
    kwargs = {
        "model": model, "max_tokens": max_tokens, "thinking": {"type": "disabled"},
        "messages": [{"role": "user", "content": _user_content(prompt, cache_prefix)}],
    }
    if stream:
        with client.messages.stream(**kwargs) as s:
            return first_text(s.get_final_message())
    return first_text(client.messages.create(**kwargs))


async def agenerate(prompt: str, *, project: str, location: str, model: str, max_tokens: int,
                    cache_prefix: str | None = None, stream: bool = True) -> str:
    """Non-blocking `complete()` — run the blocking Vertex call in a worker thread."""
    return await asyncio.to_thread(complete, prompt, project=project, location=location, model=model,
                                   max_tokens=max_tokens, cache_prefix=cache_prefix, stream=stream)


_OCR_PROMPT = (
    "Transcribe ALL text in this image verbatim. If it is a diagram, screenshot, chart or table, also "
    "briefly describe its structure, labels and relationships. Output plain text only — no preamble."
)


def describe_image(data: bytes, *, media_type: str, project: str, location: str, model: str,
                   max_tokens: int = 1500, prompt: str | None = None) -> str:
    """Transcribe/describe an image via Claude-on-Vertex vision; returns its first text block. `data`
    must already be a vision-accepted type (image/png|jpeg|gif|webp) — see extract._vision_payload."""
    import base64

    from anthropic import AnthropicVertex

    client = AnthropicVertex(project_id=project, region=location)
    b64 = base64.standard_b64encode(data).decode("ascii")
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
        {"type": "text", "text": prompt or _OCR_PROMPT},
    ]
    return first_text(client.messages.create(
        model=model, max_tokens=max_tokens, thinking={"type": "disabled"},
        messages=[{"role": "user", "content": content}]))
