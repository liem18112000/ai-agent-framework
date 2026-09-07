"""Retrieval facade (M1) — one dispatch point over the memory backend.

`MEMORY_BACKEND` selects the read path:
  * gcs (default)      — the GCS link-graph predicates (`common.memory.graph_index`); today's behaviour.
  * hybrid             — read Postgres, fall back to the graph on any miss/error (safe dark launch).
  * postgres           — read Postgres authoritative (still falls back on error, so a DB blip degrades
                         rather than breaks).

M1 wires the `search-memory` read through here; the explore-loop predicates and lesson recall move
onto the facade in M4 (they need the async store + query embeddings). Best-effort — never raises.
"""

from __future__ import annotations

import os

from common.memory.graph_index import match_index_nodes
from common.monitoring import get_logger

log = get_logger("memory.retrieve")


def backend() -> str:
    return os.environ.get("MEMORY_BACKEND", "gcs").lower()


def _graph_search(bank, query: str) -> list[dict]:
    graph, _ = bank.load_index()
    return match_index_nodes(graph, query)


async def search_nodes(bank, query: str, *, store=None) -> list[dict]:
    """Index nodes matching `query`, as `{id,type,title}` dicts. Postgres (hybrid/postgres) when a
    store is available, else the GCS graph. A Postgres error/empty-in-hybrid degrades to the graph."""
    if backend() in ("hybrid", "postgres"):
        store = store or _build_store()  # self-build so callers (search-memory) needn't wire one
        if store is not None:
            try:
                rows = await store.search(q_text=query, q_embed=await _query_embedding(query))
                if rows or backend() == "postgres":
                    return rows
            except Exception as exc:  # noqa: BLE001 — best-effort; fall back to the graph
                log.warning("memory.retrieve: pg search failed (%s); using graph", exc)
    return _graph_search(bank, query)


async def recall_lessons(bank, *, seed_refs: set[str], query_text: str = "", limit: int = 5) -> list[str]:
    """Prior lessons for a run — structural (source_refs ∩ seed_refs) ∪ semantic (vector-nearest,
    shared-scope). Postgres when a DB backend is selected + a store builds; else the structural GCS
    recall (`learn.recall_lessons`). Best-effort — any error falls back to the graph path."""
    if backend() in ("hybrid", "postgres"):
        store = _build_store()
        if store is not None:
            try:
                q_embed = await _query_embedding(query_text) if query_text else None
                hits = await store.recall(seed_refs=seed_refs, q_embed=q_embed, limit=limit)
                if hits or backend() == "postgres":
                    return hits
            except Exception as exc:  # noqa: BLE001 — recall is best-effort; fall back to the graph
                log.warning("memory.retrieve: pg recall failed (%s); using graph", exc)
    from common.learn import recall_lessons as _graph_recall

    return _graph_recall(bank, seed_refs=seed_refs, limit=limit)


def _build_store():
    """Lazily build the pg store (None if no DB). Lazy import keeps the gcs path pg-free."""
    from common.memory.pg import build_store

    return build_store()


async def _query_embedding(query: str):
    """Embed the query (RETRIEVAL_QUERY) for the vector arm, or None when Vertex isn't configured
    (→ the store runs lexical-only). Lazy import keeps the gcs path free of the pg/embed modules."""
    if not query:
        return None
    from common.memory.pg import embed

    if not embed.embed_configured():
        return None
    return (await embed.aembed_query(query)) or None
