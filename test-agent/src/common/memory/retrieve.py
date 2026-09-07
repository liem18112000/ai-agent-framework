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
    if backend() in ("hybrid", "postgres") and store is not None:
        try:
            rows = await store.search(q_text=query, q_embed=await _query_embedding(query))
            if rows or backend() == "postgres":
                return rows
        except Exception as exc:  # noqa: BLE001 — recall is best-effort; fall back to the graph
            log.warning("memory.retrieve: pg search failed (%s); using graph", exc)
    return _graph_search(bank, query)


async def _query_embedding(query: str):
    """Embed the query (RETRIEVAL_QUERY) for the vector arm, or None when Vertex isn't configured
    (→ the store runs lexical-only). Lazy import keeps the gcs path free of the pg/embed modules."""
    if not query:
        return None
    from common.memory.pg import embed

    if not embed.embed_configured():
        return None
    return (await embed.aembed_query(query)) or None
