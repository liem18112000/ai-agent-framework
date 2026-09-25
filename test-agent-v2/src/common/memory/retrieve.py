"""Retrieval facade (M1) — one dispatch point over the memory backend."""

from __future__ import annotations

import asyncio
import os

from common.memory.graph_index import match_index_nodes
from common.memory.vector_store import VectorStore
from common.monitoring import get_logger

log = get_logger("memory.retrieve")

# MEMORY_BACKEND values that consult the VectorStore before the GCS graph index. `gcs` (the default)
# stays graph-only; a None store still falls back to the graph for any of these.
_STORE_BACKENDS = ("hybrid", "postgres", "memory")


def backend() -> str:
    return os.environ.get("MEMORY_BACKEND", "gcs").lower()


def _graph_search(bank, query: str) -> list[dict]:
    graph, _ = bank.load_index()
    # MEM-10: project to the same {id,type,title} shape the pg arm returns (shared result contract).
    return [{"id": n.get("id", ""), "type": n.get("type", ""), "title": n.get("title") or ""}
            for n in match_index_nodes(graph, query)]


async def search_nodes(bank, query: str, *, store: VectorStore | None = None) -> list[dict]:
    """Index nodes matching `query`, as `{id,type,title}` dicts; the VectorStore in hybrid/postgres mode."""
    if backend() in _STORE_BACKENDS:
        store = store or _build_store()
        if store is not None:
            try:
                rows = await store.search(q_text=query, q_embed=await _query_embedding(query))
                if rows or backend() == "postgres":
                    return rows
            except Exception as exc:  # noqa: BLE001 — best-effort; fall back to the graph
                log.warning("memory.retrieve: pg search failed (%s); using graph", exc)
    return _graph_search(bank, query)


async def recall_lessons(bank, *, seed_refs: set[str], query_text: str = "", limit: int = 5,
                         steps: tuple[str, ...] = ()) -> list[str]:
    """Prior lessons for a run — structural (source_refs ∩ seed_refs) ∪ semantic (vector-nearest).
    `steps` (R1) PREFERS lessons earned at the caller's own position; it never excludes the rest."""
    if backend() in _STORE_BACKENDS:
        store = _build_store()
        if store is not None:
            try:
                q_embed = await _query_embedding(query_text) if query_text else None
                hits = await store.recall(seed_refs=seed_refs, q_embed=q_embed, limit=limit,
                                          steps=steps)
                if hits or backend() == "postgres":
                    return hits
            except Exception as exc:  # noqa: BLE001 — recall is best-effort; fall back to the graph
                log.warning("memory.retrieve: pg recall failed (%s); using graph", exc)
    from common.learn import recall_lessons as _graph_recall

    # INT-03: the GCS recall does blocking bucket round-trips (iter_lessons reads each lesson sidecar);
    # run it off the event loop so a RECALL_LESSONS-on turn can't stall Cloud Run's request loop.
    return await asyncio.to_thread(_graph_recall, bank, seed_refs=seed_refs, limit=limit, steps=steps)


def _build_store() -> VectorStore | None:
    """Lazily build the selected VectorStore (VECTOR_BACKEND; pgvector default → None when no DB).
    Lazy import keeps the gcs path free of the pg/vector adapters."""
    from common.memory.vector_factory import build_vector_store

    return build_vector_store()


async def _query_embedding(query: str):
    """Embed the query (RETRIEVAL_QUERY) for the vector arm, or None when Vertex isn't configured."""
    if not query:
        return None
    from common.memory.pg import embed

    return (await embed.aembed_query(query)) or None if embed.embed_configured() else None
