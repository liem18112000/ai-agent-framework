"""F5 — memory-graph visualisation: read memory_node + memory_edge and render the force-directed HTML.

Prefers the pgvector projection (the tables the user asked about); when no DB is configured (offline,
tests) it degrades to the GCS knowledge index, which carries the same node/edge shape. Pure read —
returns the HTML string; the caller (admin verb / CLI) writes or Artifact-publishes it."""

from __future__ import annotations

import asyncio

from common.admin._shared import _table_names
from common.admin.graph_html import build_memory_graph_html

_NODE_COLS = "id, type, kind, title, synopsis"


async def memory_graph_html(bank, engine, *, title: str = "Memory graph", node_cap: int = 600) -> str:
    """Render memory_node/memory_edge as a force-directed HTML page. pgvector first, GCS index fallback."""
    src = await _read_pg(engine) if engine is not None else None
    source = "pgvector (memory_node/memory_edge)"
    if src is None:
        src = await asyncio.to_thread(_read_index, bank)  # blocking GCS off the loop
        source = "GCS knowledge index"
    nodes, edges = src
    return build_memory_graph_html(nodes, edges, title=title, source=source, node_cap=node_cap)


async def _read_pg(engine) -> tuple[list[dict], list[dict]] | None:
    """Read all rows from memory_node + memory_edge, or None when the tables aren't there."""
    from sqlalchemy import text

    if "memory_node" not in set(await _table_names(engine)):
        return None
    async with engine.connect() as conn:
        nodes = [dict(r) for r in (await conn.execute(text(f"SELECT {_NODE_COLS} FROM memory_node"))).mappings()]
        edges = [dict(r) for r in (await conn.execute(
            text("SELECT source_id, target FROM memory_edge"))).mappings()]
    return nodes, edges


def _read_index(bank) -> tuple[list[dict], list[dict]]:
    """Fallback: the GCS index graph — nodes carry id/type/title (no synopsis), edges source_id/target."""
    graph, _ = bank.load_index()
    nodes = [{"id": n["id"], "type": n.get("type", "?"), "title": n.get("title", ""), "synopsis": ""}
             for n in graph.nodes.values()]
    edges = [{"source_id": e.get("source_id"), "target": e.get("target")} for e in graph.edges.values()]
    return nodes, edges
