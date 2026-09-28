"""The grounded context pack a refine session reads: notes + link graph + gaps."""

from __future__ import annotations

from common.models import (
    INSIGHT,
    Graph,
    Pack,
)
from common.monitoring import get_logger

log = get_logger("interrogate.pack")


def load_pack(bank, context_id: str, *, seed: str = "", gaps: list[str] | None = None) -> Pack:
    """Read the pack for `context_id` — the nodes THIS context gathered, not the whole bank."""
    graph, _ = bank.load_index()
    notes = [
        note for node in graph.nodes.values() if node.get("type") != INSIGHT
        and (note := bank.read_note(node["id"], node["type"])) is not None and note.run_id == context_id
    ]
    if not notes and graph.nodes:
        log.warning("load_pack: %d global nodes but 0 own %s (run_id mismatch) — scoped pack is empty", len(graph.nodes), context_id)
    scoped = _scoped_graph(graph, {n.id for n in notes})
    return Pack(context_id=context_id, notes=notes, graph=scoped, gaps=list(gaps or []), seed=seed)


def _scoped_graph(graph: Graph, keep: set[str]) -> Graph:
    """A copy of `graph` restricted to `keep` node ids and each kept node's outgoing edges."""
    scoped = Graph()
    scoped.nodes = {nid: n for nid, n in graph.nodes.items() if nid in keep}
    scoped.edges = {k: e for k, e in graph.edges.items() if e.get("source_id") in keep}
    return scoped
