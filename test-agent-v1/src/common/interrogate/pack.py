"""The grounded context pack a refine session reads: notes + link graph + gaps.

Built from the Memory Bank the gather loop wrote (`load_pack`) or handed straight
from a fresh crawl. `summary_text()` renders it compactly for the LLM prompt.
"""

from __future__ import annotations

from common.models import (
    INSIGHT,
    Graph,
    Pack,  # re-exported so `from common.interrogate.pack import Pack` keeps working
)
from common.monitoring import get_logger

log = get_logger("interrogate.pack")


def load_pack(bank, context_id: str, *, seed: str = "", gaps: list[str] | None = None) -> Pack:
    """Read the pack for `context_id` — the nodes THIS context gathered, not the whole bank.

    B0 (de-bias): scope the interrogation corpus to the context's own run. The Memory Bank
    index is GLOBAL — it merges every run's nodes — so reading all of it lets a saturated,
    unrelated domain (e.g. a memory bank full of ePost ZIP-import work) bleed into the questions
    and make refine/define interrogate the wrong ticket. Every crawl stamps each note with
    run_id == context_id (see knowledge_gathering.loop.crawl), and the MCP bridge reuses one
    context_id for gather → refine → define, so filtering the loaded notes by run_id yields
    exactly this context's own node set. See docs RESEARCH §7.3 B0.

    Gaps are not stored as graph nodes, so a bank load can't recover a prior run's gaps;
    pass them in when known (e.g. straight from a fresh crawl's CrawlResult.gaps).

    INSIGHT nodes are skipped: they are refinement outputs, not crawl notes, and their
    JSON sidecar deserializes to an `Insight` (extra fields like `kind`), not a `Note`.
    """
    graph, _ = bank.load_index()
    notes = [
        note
        for node in graph.nodes.values()
        if node.get("type") != INSIGHT
        and (note := bank.read_note(node["id"], node["type"])) is not None
        and note.run_id == context_id
    ]
    if not notes and graph.nodes:
        # Every note filtered out but the bank is non-empty → the context_id never matched a
        # gathered run_id (a stale/mismatched id). Refuse to fall back to the global bank: an
        # empty, honestly-scoped pack ("run gather first") beats interrogating the wrong ticket.
        log.warning(
            "load_pack: %d global nodes but 0 own %s (run_id mismatch) — scoped pack is empty",
            len(graph.nodes), context_id,
        )
    scoped = _scoped_graph(graph, {n.id for n in notes})
    return Pack(context_id=context_id, notes=notes, graph=scoped, gaps=list(gaps or []), seed=seed)


def _scoped_graph(graph: Graph, keep: set[str]) -> Graph:
    """A copy of `graph` restricted to `keep` node ids and each kept node's outgoing edges.

    Keeps the Pack's graph consistent with its (run-scoped) notes; edge targets may point at
    recorded-only links outside `keep` — that's a followed/recorded link, kept for provenance.
    """
    scoped = Graph()
    scoped.nodes = {nid: n for nid, n in graph.nodes.items() if nid in keep}
    scoped.edges = {k: e for k, e in graph.edges.items() if e.get("source_id") in keep}
    return scoped
