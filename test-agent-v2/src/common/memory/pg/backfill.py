"""M5 backfill — (re)derive the pgvector recall tier from the GCS record (the source of truth)."""

from __future__ import annotations

from common.memory.pg.project import drain_index, enqueue_index
from common.monitoring import get_logger

log = get_logger("memory.backfill")


def enqueue_all(bank) -> int:
    """Enqueue an IndexJob for every node in the GCS index (deduped). Returns the node count."""
    graph, _ = bank.load_index()
    for node in graph.nodes.values():
        nid = node.get("id")
        if nid:
            enqueue_index(bank, nid, node.get("type", ""))
    return len(graph.nodes)


async def backfill(bank, store, *, embedder=None, batch: int = 100, max_passes: int = 1000) -> tuple[int, int]:
    """Enqueue every index node, then drain in batches until the queue is empty (or a pass makes no"""
    total = enqueue_all(bank)
    projected = 0
    for _ in range(max_passes):
        n = await drain_index(bank, store, embedder=embedder, max_jobs=batch)
        projected += n
        if n == 0:
            break
    try:
        await store.ensure_ann_index()
    except Exception as exc:  # noqa: BLE001 — index build must not fail the backfill
        log.warning("backfill: ANN index build skipped (%s)", exc)
    log.info("backfill: %d node(s) in index, %d projected", total, projected)
    return total, projected
