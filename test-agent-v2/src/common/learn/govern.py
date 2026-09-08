"""Lesson governance (L5): human veto + read-only search over the durable lesson store."""

from __future__ import annotations

from common.learn.store import iter_lessons


def veto_lesson(bank, insight_id: str) -> bool:
    """Retract a lesson. Keeps the sidecar as a `vetoed` tombstone (so capture never re-learns it)"""
    ins = bank.read_insight(insight_id)
    if ins is None:
        return False
    ins.status = "vetoed"
    bank.upsert_insight(ins)
    bank.update_index(lambda g: _drop_node(g, insight_id))
    return True


def _drop_node(graph, node_id: str) -> None:
    graph.nodes.pop(node_id, None)
    for key in [k for k, e in graph.edges.items()
                if e.get("source_id") == node_id or e.get("target") == node_id]:
        graph.edges.pop(key, None)


def search_lessons(bank, query: str = "") -> list[dict]:
    """Active lessons whose statement matches `query` (all if empty). Read-only."""
    q = query.lower()
    return [
        {"id": i.id, "kind": i.kind, "statement": i.statement,
         "confidence": i.confidence, "source_refs": i.source_refs}
        for i in iter_lessons(bank) if not q or q in i.statement.lower()
    ]
