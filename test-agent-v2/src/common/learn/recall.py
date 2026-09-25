"""Recall prior lessons for a new run — grounded to the seed (B5), off the memory well (L4)."""

from __future__ import annotations

from common.learn.store import iter_lessons
from common.monitoring import get_logger

log = get_logger("learn.recall")

#: R1 — the pipeline steps that share one POSITION (openrig's "seat"): a lesson earned while
#: gathering is about the same work as refining it; one earned while implementing is about the same
#: work as defining. `origin_step` is only ever written as "gather" or "implement" (the two capture
#: sites), while recall runs at "refine"/"define" — so the useful unit is the AGENT, not the step.
AGENT_STEPS = {"KGA": ("gather", "refine"), "TPD": ("define", "implement")}


def recall_lessons(bank, *, seed_refs: set[str], limit: int = 5, steps: tuple[str, ...] = ()) -> list[str]:
    """Active lessons grounded to the seed (a source_ref in `seed_refs`), own-position first, then
    human-confidence, then newest. `steps` PREFERS lessons earned at those positions — it never
    excludes the others, so a cold position still recalls everything it used to."""
    try:
        hits = [i for i in iter_lessons(bank) if seed_refs and set(i.source_refs) & seed_refs]
        # INT-02: newest-first, but any high-confidence lesson still wins. Two stable passes —
        # created_at DESC, then float high-confidence to the front (Python sort is stable, so the
        # newest-first order is kept within each confidence band). created_at is an ISO string, so a
        # lexical sort IS chronological. The old single ascending key surfaced the OLDEST lessons and
        # hid later CORRECTIONs (lessons are never "high", so created_at ascending dominated).
        hits.sort(key=lambda i: i.created_at, reverse=True)
        hits.sort(key=lambda i: i.confidence != "high")
        # R1: own-position last = HIGHEST priority (stable sort). Prefer, never exclude — a position
        # that has learned nothing still recalls every lesson it used to.
        if steps:
            hits.sort(key=lambda i: i.origin_step not in steps)
        return [i.statement for i in hits[:limit]]
    except Exception as exc:  # noqa: BLE001 — recall is best-effort
        log.warning("learn: recall failed (%s); none", exc)
        return []
