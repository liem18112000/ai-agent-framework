"""Claude-on-Vertex (AnthropicVertex) client helpers and env-driven config."""

from __future__ import annotations

import os
import random
import time
from functools import cache
from typing import Any

from common.llm import meter
from common.monitoring import get_logger

log = get_logger("llm.vertex")

_ENV_KEYS = ("VERTEX_PROJECT", "VERTEX_LOCATION", "VERTEX_MODEL")

# Transient HTTP statuses worth retrying (429 rate-limit, 5xx incl. 529 overloaded).
_RETRY_STATUS = frozenset({429, 500, 502, 503, 529})
_MAX_ATTEMPTS = 3
_BASE_BACKOFF = 0.5  # seconds; exp backoff 0.5s, 1s (+jitter)


@cache  # one (project, location) per process — client setup is not free
def _client(project: str, location: str):
    """Process-wide AnthropicVertex singleton. Safe to share across the to_thread workers (the client
    is built for concurrent use); reused so we don't redo credential/transport setup on every call."""
    from anthropic import AnthropicVertex

    # Explicit max_retries/timeout: the SDK retries connection blips before our app-level loop even
    # sees them; timeout is generous for long define/implement generations.
    return AnthropicVertex(project_id=project, region=location, max_retries=2, timeout=600.0)


def _is_transient(exc: Exception) -> bool:
    """True for retryable Vertex/Anthropic failures: connection drops, 429/5xx, overloaded."""
    from anthropic import APIConnectionError, APIStatusError

    if isinstance(exc, APIConnectionError):
        return True
    if isinstance(exc, APIStatusError) and getattr(exc, "status_code", None) in _RETRY_STATUS:
        return True
    return "overloaded" in str(exc).lower()  # mid-stream overloaded_error not tied to a status


def _with_retry(run):
    """Call `run()` with bounded exp-backoff retry on transient errors; re-raise 4xx/auth immediately."""
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            return run()
        except Exception as exc:  # re-raised below unless transient with attempts left
            if attempt >= _MAX_ATTEMPTS or not _is_transient(exc):
                raise
            delay = _BASE_BACKOFF * 2 ** (attempt - 1) + random.uniform(0, 0.1)
            log.warning("vertex call failed (attempt %d/%d), retrying in %.1fs: %s",
                        attempt, _MAX_ATTEMPTS, delay, exc)
            time.sleep(delay)


def vertex_config() -> tuple[str, str, str] | None:
    """Return (project, location, model) from env, or None if any is unset."""
    proj, loc, model = (os.environ.get(k) for k in _ENV_KEYS)
    return (proj, loc, model) if (proj and loc and model) else None


def first_text(msg: Any) -> str:
    """Return the first text block from an Anthropic message, skipping non-text blocks."""
    return next((b.text for b in msg.content if getattr(b, "type", None) == "text"), "")


# Prompt-cache TTL for `cache_prefix`. The 5-minute default is WRONG for every caller we have: the
# define/refine rounds are separated by a human answering the questions (minutes to hours), and one
# implement round runs a dozen serial batches well past 5 minutes — so the prefix expired between
# calls and every call paid the 1.25x write again and never read. At "1h" the write costs 2x once and
# each later call reads at ~0.1x, which beats uncached from the 3rd call on; every cache_prefix site
# here makes at least 4 (4 define rounds + brief; questions + understanding per refine pass).
_CACHE_TTL = "1h"

# Below the model's minimum cacheable prefix the API silently ignores cache_control (no error, no
# write, no read). claude-sonnet-5's minimum is 1024 tokens; this is that in characters at the usual
# ~4 chars/token, used only to log why a cache never hit.
_MIN_CACHEABLE_CHARS = 4096


def _user_content(prompt: str, cache_prefix: str | None):
    """The `messages` content: a plain string, or a [cached-prefix, prompt] block list when a
    stable `cache_prefix` is given (Anthropic prompt caching — cache_control: ephemeral, 1h TTL)."""
    if not cache_prefix:
        return prompt
    if len(cache_prefix) < _MIN_CACHEABLE_CHARS:
        log.debug("cache_prefix is %d chars (< ~%d): under the model's minimum cacheable prefix, so "
                  "cache_control is ignored and this call bills uncached",
                  len(cache_prefix), _MIN_CACHEABLE_CHARS)
    return [
        {"type": "text", "text": cache_prefix,
         "cache_control": {"type": "ephemeral", "ttl": _CACHE_TTL}},
        {"type": "text", "text": prompt},
    ]


def complete(prompt: str, *, project: str, location: str, model: str, max_tokens: int,
             cache_prefix: str | None = None, stream: bool = True, label: str = "complete") -> str:
    """Run one Claude-on-Vertex completion and return its first text block.

    Streams by default (`messages.stream`) — same result, but robust on long generations (keeps the
    connection alive past read timeouts). When `cache_prefix` is given, that stable block is
    **prompt-cached**, so repeated calls sharing it (e.g. the 4 define rounds over one pack) are
    materially faster and ~cheaper on the cached tokens; set `stream=False`/`cache_prefix=None` to opt out.

    `label` names the calling stage on the token meter — without it a snapshot says how much we spent
    but never where, which is the only question worth asking."""
    client = _client(project, location)
    kwargs = {
        "model": model, "max_tokens": max_tokens, "thinking": {"type": "disabled"},
        "messages": [{"role": "user", "content": _user_content(prompt, cache_prefix)}],
    }

    def _stream_once():
        with client.messages.stream(**kwargs) as s:  # inside retry: a mid-stream drop re-runs the call
            return s.get_final_message()

    msg = _with_retry(_stream_once if stream else lambda: client.messages.create(**kwargs))
    meter.record_message(label, getattr(msg, "usage", None))
    return first_text(msg)


_OCR_PROMPT = (
    "Transcribe ALL text in this image verbatim. If it is a diagram, screenshot, chart or table, also "
    "briefly describe its structure, labels and relationships. Output plain text only — no preamble."
)


def describe_image(data: bytes, *, media_type: str, project: str, location: str, model: str,
                   max_tokens: int = 1500, prompt: str | None = None) -> str:
    """Transcribe/describe an image via Claude-on-Vertex vision; returns its first text block. `data`
    must already be a vision-accepted type (image/png|jpeg|gif|webp) — see extract._vision_payload."""
    import base64

    client = _client(project, location)
    b64 = base64.standard_b64encode(data).decode("ascii")
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
        {"type": "text", "text": prompt or _OCR_PROMPT},
    ]
    msg = client.messages.create(
        model=model, max_tokens=max_tokens, thinking={"type": "disabled"},
        messages=[{"role": "user", "content": content}])
    meter.record_message("vision.ocr", getattr(msg, "usage", None))
    return first_text(msg)
