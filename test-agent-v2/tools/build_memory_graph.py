#!/usr/bin/env python
"""Render the memory graph (memory_node + memory_edge) to a self-contained force-directed HTML page.

Usage:
    python tools/build_memory_graph.py [out.html] [title]

Reads pgvector (DB_* / STORE_BACKEND env, same as the agents) when configured, else the GCS knowledge
index, and writes one self-contained page (graphify-style node-link view). Publish it via Artifact."""
import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from common.admin import memory_graph_html
from common.memory import MemoryBank
from common.store import build_object_store


async def _run(out: pathlib.Path, title: str) -> None:
    try:
        from common.db import get_engine

        engine = get_engine()
    except Exception:  # noqa: BLE001 — no DB configured → fall back to the GCS index
        engine = None
    html = await memory_graph_html(MemoryBank(build_object_store()), engine, title=title)
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out} ({len(html)} chars)")


def main() -> None:
    out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "memory-graph.html")
    title = sys.argv[2] if len(sys.argv) > 2 else "Memory graph"
    asyncio.run(_run(out, title))


if __name__ == "__main__":
    main()
