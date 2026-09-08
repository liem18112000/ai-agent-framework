"""M5 backfill — (re)derive the pgvector recall tier from the GCS record (the source of truth).

Reuses the projector end-to-end: enqueue an `IndexJob` for every node in the GCS knowledge index,
then drain the queue into Postgres (upsert_node/edges + embed) until empty. Because Postgres is a
*projection* of GCS, this proves the read model is droppable/re-derivable — the migration's safety
net (§8). Idempotent (ON CONFLICT + the content-hash embed skip) so re-runs are cheap; the durable
queue makes an interrupted run resumable (the next run just drains what's left).

Run once before flipping `MEMORY_BACKEND=hybrid`, and after any bulk GCS import:

    uv run python tools/backfill_memory.py
"""

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
    """Enqueue every index node, then drain in batches until the queue is empty (or a pass makes no
    progress — permanently-failing jobs stay queued rather than looping forever). Returns
    `(nodes_in_index, nodes_projected)`."""
    total = enqueue_all(bank)
    projected = 0
    for _ in range(max_passes):
        n = await drain_index(bank, store, embedder=embedder, max_jobs=batch)
        projected += n
        if n == 0:  # queue empty, or only permanently-failing jobs remain
            break
    try:  # build the ANN index once the corpus is populated (idempotent; best-effort)
        await store.ensure_ann_index()
    except Exception as exc:  # noqa: BLE001 — index build must not fail the backfill
        log.warning("backfill: ANN index build skipped (%s)", exc)
    log.info("backfill: %d node(s) in index, %d projected", total, projected)
    return total, projected


async def run() -> int:
    """CLI entrypoint: build the bank/store/embedder from env and backfill. 1 if no DB configured."""
    from common.memory.factory import build_bank
    from common.memory.pg import build_store
    from common.memory.pg.embed import build_embedder

    store = build_store()
    if store is None:
        log.error("backfill: no DB configured (set DB_* or TASK_DB_URL) — nothing to project")
        return 1
    await backfill(build_bank(), store, embedder=build_embedder())
    return 0
