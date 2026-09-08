"""Async projector (M2) — mirror of common/learn/queue.py for the pgvector index."""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
from dataclasses import asdict, dataclass

from common.memory.bank import ROOT
from common.memory.retrieve import backend
from common.models import INSIGHT
from common.monitoring import get_logger

log = get_logger("memory.project")
INDEX_QUEUE = f"{ROOT}/index/index-queue.json"


def _text_hash(text: str) -> str:
    """Content key for the embedding content-hash skip (local — a memory→learn import would invert"""
    return hashlib.sha1(text.strip().encode()).hexdigest()[:16]


_TEST_PLAN, _TEST_SCENARIO = "test-plan", "test-scenario"


@dataclass
class IndexJob:
    """A queued projection unit: one node to (re)project from GCS into Postgres."""

    id: str
    node_id: str
    node_type: str
    kind: str = ""
    created_at: str = ""


def enqueue_index(bank, node_id: str, node_type: str, kind: str = "") -> None:
    """Append an IndexJob (CAS), deduped by node id so churny re-writes don't grow the queue."""
    job = asdict(IndexJob(id=node_id, node_id=node_id, node_type=node_type, kind=kind))
    bank.mutate_json(
        INDEX_QUEUE,
        lambda q: q if any(j.get("node_id") == node_id for j in q) else [*q, job],
        default=[],
    )


def index_on_write(bank, node_id: str, node_type: str, kind: str = "") -> None:
    """MemoryBank.on_write hook: enqueue a projection when a DB-backed backend is selected."""
    if backend() == "gcs":
        return
    enqueue_index(bank, node_id, node_type, kind)


def _note_row_edges(note) -> tuple[dict, list[dict]]:
    row = {
        "id": note.id, "type": note.type, "kind": "", "title": note.title,
        "synopsis": note.synopsis, "source_url": note.source_url, "content_uri": note.source_url,
        "run_id": note.run_id, "context_id": "", "scope": "context", "status": "active",
        "confidence": note.confidence, "meta": {"depth": note.depth, "backlinks": note.backlinks},
    }
    edges = [
        {"source_id": note.id, "target": lr.canonical_url, "type": lr.type,
         "origin": lr.origin, "in_scope": lr.in_scope}
        for lr in note.links if lr.canonical_url
    ]
    return row, edges


def _insight_row_edges(ins) -> tuple[dict, list[dict]]:
    row = {
        "id": ins.id, "type": INSIGHT, "kind": ins.kind, "title": ins.statement[:80],
        "synopsis": ins.statement, "source_url": "", "content_uri": "",
        "run_id": getattr(ins, "run_id", ""), "context_id": getattr(ins, "context_id", ""),
        "scope": getattr(ins, "scope", "context"), "status": getattr(ins, "status", "active"),
        "confidence": ins.confidence,
        "meta": {"origin_step": getattr(ins, "origin_step", ""), "source_refs": list(ins.source_refs)},
    }
    edges = [
        {"source_id": ins.id, "target": ref, "type": INSIGHT, "origin": ins.kind, "in_scope": True}
        for ref in ins.source_refs if ref
    ]
    return row, edges


def _index_row_edges(graph, node_id: str, node_type: str):
    """Map a test-plan / test-scenario node from the knowledge INDEX. TPD writes these as raw JSON"""
    node = graph.nodes.get(node_id) if graph else None
    if node is None:
        return None
    title = node.get("title") or ""
    kind = node_id.rsplit(":", 1)[-1] if node_type == _TEST_SCENARIO else ""
    row = {
        "id": node_id, "type": node_type, "kind": kind, "title": title, "synopsis": title,
        "source_url": "", "content_uri": "", "run_id": "", "context_id": "",
        "scope": "context", "status": "active", "confidence": "high", "meta": {},
    }
    edges = [
        {"source_id": node_id, "target": e.get("target"), "type": e.get("type"),
         "origin": e.get("origin"), "in_scope": e.get("in_scope", True)}
        for e in graph.edges.values() if e.get("source_id") == node_id and e.get("target")
    ]
    return row, edges


def _load_row_edges(bank, node_id: str, node_type: str, graph=None):
    """Read a node back from the truth (GCS note/insight; the index for TPD plan/scenario) and map"""
    if node_type == INSIGHT:
        ins = bank.read_insight(node_id)
        return _insight_row_edges(ins) if ins is not None else None
    if node_type in (_TEST_PLAN, _TEST_SCENARIO):
        return _index_row_edges(graph, node_id, node_type)
    note = bank.read_note(node_id, node_type)
    return _note_row_edges(note) if note is not None else None


async def _flush_embeds(store, embedder, queued: list[tuple]) -> list[str]:
    """Embed a batch of (job_id, node_id, synopsis, emb_hash) in ONE embedder call, then persist"""
    if not queued:
        return []
    vecs = await embedder([syn for (_jid, _nid, syn, _h) in queued])
    if len(vecs) != len(queued):
        return []
    out: list[str] = []
    for (job_id, node_id, _syn, emb_hash), vec in zip(queued, vecs):
        try:
            if vec:
                await store.set_embedding(node_id, vec, emb_hash=emb_hash)
            out.append(job_id)
        except Exception as exc:  # noqa: BLE001 — one set_embedding failure retries just that node
            log.warning("memory: set_embedding %s failed (%s); left for retry", node_id, exc)
    return out


async def drain_index(bank, store, *, embedder=None, max_jobs: int = 50,
                      budget_s: float | None = None, embed_batch: int | None = None) -> int:
    """Project pending IndexJobs into Postgres; return how many completed. At-least-once — a job"""
    if embed_batch is None:
        embed_batch = int(os.environ.get("MEMORY_EMBED_BATCH", "16"))
    pending = await asyncio.to_thread(bank.get_json, INDEX_QUEUE, []) or []
    done: list[str] = []
    queued: list[tuple] = []
    start = time.monotonic()
    batch = pending[:max_jobs]
    graph = None
    if any(r.get("node_type") in (_TEST_PLAN, _TEST_SCENARIO) for r in batch):
        graph = (await asyncio.to_thread(bank.load_index))[0]
    for raw in batch:
        node_id = raw.get("node_id")
        try:
            mapped = await asyncio.to_thread(_load_row_edges, bank, node_id, raw.get("node_type", ""), graph)
            if mapped is None:
                done.append(raw["id"]); continue
            row, edges = mapped
            synopsis = row.get("synopsis") or ""
            emb_hash = _text_hash(synopsis)
            fresh = embedder is None or not synopsis or await store.embedding_fresh(node_id, emb_hash)
            await store.upsert_node(row)
            await store.upsert_edges(edges)
            if fresh:
                done.append(raw["id"])
            else:
                queued.append((raw["id"], node_id, synopsis, emb_hash))
                if len(queued) >= embed_batch:
                    done.extend(await _flush_embeds(store, embedder, queued))
                    queued = []
        except Exception as exc:  # noqa: BLE001 — one bad job must not block the drain
            log.warning("memory: index job %s failed (%s); left for retry", node_id, exc)
        if budget_s is not None and time.monotonic() - start >= budget_s:
            break
    done.extend(await _flush_embeds(store, embedder, queued))
    if done:
        ids = set(done)
        await asyncio.to_thread(
            bank.mutate_json, INDEX_QUEUE, lambda q: [j for j in q if j.get("id") not in ids], default=[]
        )
    log.info("memory: projected %d node(s)", len(done))
    return len(done)


async def maybe_drain_index(bank) -> int:
    """Head-of-request projector flush — build the store + drain when a DB backend is selected."""
    if bank is None or backend() == "gcs":
        return 0
    try:
        from common.memory.pg import build_store
        from common.memory.pg.embed import build_embedder

        store = build_store()
        if store is None:
            return 0
        budget = float(os.environ.get("MEMORY_DRAIN_BUDGET_S", "8"))
        return await drain_index(bank, store, embedder=build_embedder(), max_jobs=500, budget_s=budget)
    except Exception as exc:  # noqa: BLE001 — best-effort; never break the request
        log.warning("memory: index drain skipped (%s)", exc)
        return 0
