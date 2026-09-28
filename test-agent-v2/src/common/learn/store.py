"""Read lesson Insights from the memory-bank index (shared by recall + governance)."""

from __future__ import annotations

from common.models import CORRECTION, GOTCHA, INSIGHT, LESSON, TOKEN_SAVING

_KINDS = (LESSON, CORRECTION, GOTCHA, TOKEN_SAVING)
_KIND_SET = frozenset(_KINDS)


def iter_lessons(bank, *, active_only: bool = True):
    """Yield lesson-kind Insights from the index (reads each lesson's sidecar).

    INT-03: an insight's edges carry `origin == insight.kind` (models/graph.add_insight), so a
    sidecar read is skipped for any insight whose edges PROVE it is a non-lesson (decision/assumption/
    gap-seed) — cutting the fan-out from O(all insights) to O(lessons). Edgeless insights stay
    ambiguous (the rare empty-index lesson), so they are still read to preserve behaviour; the sidecar
    remains the authoritative kind/status filter."""
    graph, _ = bank.load_index()
    origins: dict[str, set[str]] = {}
    for e in graph.edges.values():
        sid = e.get("source_id")
        if sid is not None:
            origins.setdefault(sid, set()).add(e.get("origin"))
    for node in graph.nodes.values():
        if node.get("type") != INSIGHT:
            continue
        node_origins = origins.get(node["id"])
        if node_origins and not (node_origins & _KIND_SET):
            continue  # edges prove this insight is not a lesson — skip the GCS round-trip
        ins = bank.read_insight(node["id"])
        if ins is None or ins.kind not in _KINDS or (active_only and ins.status != "active"):
            continue
        yield ins
