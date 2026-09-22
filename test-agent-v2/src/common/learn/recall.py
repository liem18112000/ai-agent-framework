"""Recall prior lessons for a new run — grounded to the seed (B5), off the memory well (L4)."""

from __future__ import annotations

from common.learn.store import iter_lessons
from common.monitoring import get_logger

log = get_logger("learn.recall")


def recall_lessons(bank, *, seed_refs: set[str], limit: int = 5) -> list[str]:
    """Active lessons grounded to the seed (a source_ref in `seed_refs`), human-confidence first,"""
    try:
        hits = [i for i in iter_lessons(bank) if seed_refs and set(i.source_refs) & seed_refs]
        # INT-02: newest-first, but any high-confidence lesson still wins. Two stable passes —
        # created_at DESC, then float high-confidence to the front (Python sort is stable, so the
        # newest-first order is kept within each confidence band). created_at is an ISO string, so a
        # lexical sort IS chronological. The old single ascending key surfaced the OLDEST lessons and
        # hid later CORRECTIONs (lessons are never "high", so created_at ascending dominated).
        hits.sort(key=lambda i: i.created_at, reverse=True)
        hits.sort(key=lambda i: i.confidence != "high")
        return [i.statement for i in hits[:limit]]
    except Exception as exc:  # noqa: BLE001 — recall is best-effort
        log.warning("learn: recall failed (%s); none", exc)
        return []
