"""Per-process LLM token meter — what each stage actually spends, in tokens.

Every Vertex/Anthropic response carries a ``usage`` block; until now we threw all of them away, so
"where do the tokens go?" had no answer and any optimization was guesswork. Both model paths feed
these counters — the direct ``complete()`` path (``common.llm.vertex``) and the ADK/LiteLlm path
(``common.testplan.llm.adk.run_json_agent``) — so one snapshot covers the whole pipeline.

Read ``cache_read`` against ``cache_write``: a prompt-cached prefix that never reads (cache_read
stays 0 across a run that made several calls sharing one prefix) means the cache is not working —
a silent invalidator, a prefix under the model's minimum cacheable size, or a TTL that expired
between calls — and those tokens cost 1.25-2x instead of 0.1x.

Counters are process-local and best-effort: a missing/partial ``usage`` records what it has. Nothing
here is on the critical path, so a meter failure must never fail a generation.
"""

from __future__ import annotations

import contextlib
import threading
from contextvars import ContextVar
from dataclasses import asdict, dataclass, fields

from common.monitoring import get_logger

log = get_logger("llm.meter")

_LOCK = threading.Lock()  # ponytail: one global lock; per-label locks only if this ever gets hot


@dataclass
class TokenUsage:
    """One label's running totals. ``input`` excludes cached tokens (the API reports them apart)."""

    calls: int = 0
    input: int = 0
    output: int = 0
    cache_read: int = 0      # served from the prompt cache (~0.1x input price)
    cache_write: int = 0     # written to the prompt cache (1.25x at 5m TTL, 2x at 1h)

    def add(self, other: TokenUsage) -> None:
        for f in fields(self):
            setattr(self, f.name, getattr(self, f.name) + getattr(other, f.name))


#: The run these counters belong to. A ContextVar rather than a parameter on `record()` because the
#: run id is known at ONE place (the stage entry point) and the ~15 call sites that spend tokens are
#: several frames below it — threading it through every signature would be churn for no gain.
#: `asyncio.to_thread` copies the context, so the blocking off-loop calls stay attributed correctly.
_RUN: ContextVar[str] = ContextVar("token_meter_run", default="")

#: run_id -> label -> usage. The "" run holds anything recorded outside a `run_scope`.
_TOTALS: dict[str, dict[str, TokenUsage]] = {}


@contextlib.contextmanager
def run_scope(run_id: str):
    """Attribute everything recorded inside this block to `run_id` (nestable, async-safe)."""
    token = _RUN.set(run_id or "")
    try:
        yield
    finally:
        _RUN.reset(token)


def current_run() -> str:
    return _RUN.get()


def record(label: str, *, input: int = 0, output: int = 0,
           cache_read: int = 0, cache_write: int = 0) -> None:
    """Add one call's usage under ``label`` (the stage: agent name, or the `complete()` caller)."""
    one = TokenUsage(calls=1, input=input, output=output,
                     cache_read=cache_read, cache_write=cache_write)
    with _LOCK:
        _TOTALS.setdefault(_RUN.get(), {}).setdefault(label or "unlabelled", TokenUsage()).add(one)
    log.debug("tokens %s: in=%d out=%d cache_read=%d cache_write=%d",
              label, input, output, cache_read, cache_write)


def record_message(label: str, usage) -> None:
    """Record an Anthropic ``message.usage`` object (best-effort — a missing field counts as 0)."""
    if usage is None:
        return
    record(label,
           input=getattr(usage, "input_tokens", 0) or 0,
           output=getattr(usage, "output_tokens", 0) or 0,
           cache_read=getattr(usage, "cache_read_input_tokens", 0) or 0,
           cache_write=getattr(usage, "cache_creation_input_tokens", 0) or 0)


def snapshot(run_id: str | None = None, *, drain: bool = False) -> dict[str, dict]:
    """Per-label totals plus a ``TOTAL`` row, as plain dicts (JSON-safe, for logs / admin).

    ``run_id=None`` aggregates every run this process has seen; pass a run id to scope it, or ``""``
    for the calls recorded outside any ``run_scope``.

    ``drain=True`` also CLEARS what it returned, so the caller OWNS those numbers. `persist_usage`
    uses it: the counters are process-cumulative and a chunked run persists on every chunk, so
    folding an un-drained snapshot into the stored blob re-adds every earlier chunk (3 chunks on one
    warm instance stored 2x the real bill, and the admin view showed 3x). It also stops `_TOTALS`
    growing for the life of the process."""
    with _LOCK:
        runs = _TOTALS if run_id is None else {run_id: _TOTALS.get(run_id, {})}
        out: dict[str, TokenUsage] = {}
        for by_label in runs.values():
            for label, usage in by_label.items():
                out.setdefault(label, TokenUsage()).add(usage)
        if drain:
            for r in list(runs):
                _TOTALS.pop(r, None)
    total = TokenUsage()
    for v in out.values():
        total.add(v)
    snap = {k: asdict(v) for k, v in out.items()}
    snap["TOTAL"] = asdict(total)
    return snap


def runs() -> list[str]:
    """Run ids this process has recorded against."""
    with _LOCK:
        return sorted(r for r in _TOTALS if r)


def reset() -> None:
    """Clear the counters (per-run accounting, and test isolation)."""
    with _LOCK:
        _TOTALS.clear()


def summary_line(run_id: str | None = None) -> str:
    """One-line total, for an end-of-stage log: the shape you scan a deploy log for."""
    t = snapshot(run_id)["TOTAL"]
    hit = t["cache_read"] / r if (r := t["cache_read"] + t["cache_write"]) else 0.0
    return (f"{t['calls']} call(s) · in={t['input']} +cached_read={t['cache_read']} "
            f"+cached_write={t['cache_write']} · out={t['output']} · cache-hit={hit:.0%}")
