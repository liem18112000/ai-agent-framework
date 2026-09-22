"""Read lesson Insights from the memory-bank index (shared by recall + governance)."""

from __future__ import annotations

from common.models import CORRECTION, GOTCHA, INSIGHT, LESSON

_KINDS = (LESSON, CORRECTION, GOTCHA)


def iter_lessons(bank, *, active_only: bool = True):
    """Yield lesson-kind Insights from the index (reads each sidecar)."""
    graph, _ = bank.load_index()
    for node in graph.nodes.values():
        if node.get("type") != INSIGHT:
            continue
        ins = bank.read_insight(node["id"])
        if ins is None or ins.kind not in _KINDS:
            continue
        if active_only and ins.status != "active":
            continue
        yield ins
