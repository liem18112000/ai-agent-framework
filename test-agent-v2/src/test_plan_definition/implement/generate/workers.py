"""Phase C — distributed scenario generation via a Pub/Sub + Cloud Run worker pool.

The coordinator (inside ``claude_scenarios``, so its synchronous contract is unchanged) splits the pack
into per-batch jobs, PUBLISHES one message per batch to a Pub/Sub topic, then POLLS GCS for the results
and merges them. WORKERS run on a separate Cloud Run service (``worker.py``) — each in its OWN process, so
they sidestep the in-process ADK/LiteLlm limits (a worker uses the direct ``complete()`` path, no ADK
Runner) — pull a job, generate, write the result blob, and ack. The judge still runs once, later, in the
assured loop over the merged scenarios.

Gated by ``TPD_GEN_MODE=workers`` (default = the synchronous per-batch path). CEILING NOTE: parallel
workers still share the per-project Vertex quota, so single-ticket latency may not improve (the A/B showed
implement is throughput-bound); C's guaranteed wins are resilience (DLQ/retry), decoupling, and scale across
many tickets. The job-build + result-merge are pure + unit-tested; publish/pull/poll need live infra.
"""

from __future__ import annotations

import asyncio
import json
import os
import time

from common.llm.parse import loads_obj
from common.testplan.llm.prompts import pack_block, scenarios_prompt
from common.testplan.llm.schemas import Scenarios
from common.testplan.models import TestData, TestPlan, TestScenario
from test_plan_definition.monitoring import get_logger

log = get_logger("llm.implement.workers")

_DEFAULT_BUDGET_S = 600.0
_RESULT_PREFIX = "workers"  # gs://<bucket>/workers/<ctx>/<run>/<batch>.txt


def enabled() -> bool:
    """True when distributed generation is opted in (``TPD_GEN_MODE=workers``)."""
    return os.environ.get("TPD_GEN_MODE", "").strip().lower() == "workers"


def build_job(result_blob: str, *, system: str, user: str, max_tokens: int) -> dict:
    """One worker job message: where to write the result, and the cached system + user prompt to run.
    The worker runs ``complete(user, cache_prefix=system, max_tokens=...)`` and writes the raw text."""
    return {"result_blob": result_blob, "system": system, "user": user, "max_tokens": max_tokens}


def result_blob(ctx: str, run: str, batch_id: int) -> str:
    return f"{_RESULT_PREFIX}/{ctx}/{run}/{batch_id}.txt"


def handle_job(data: bytes) -> None:
    """WORKER side: run one job's generation and write its raw text to GCS. Raises on failure so the
    subscriber leaves the message unacked. On the Pub/Sub path that means redelivery/dead-lettering; on
    the Redis Streams path (redis_worker.py) an unacked job stays in the PEL and is NOT auto-redelivered
    (no XAUTOCLAIM sweep — see common/queue.py) → the coordinator's poll budget elapses and its units
    degrade to the heuristic. Either way it's idempotent: the result blob is keyed by (ctx, run, batch),
    so a redelivery just overwrites."""
    from common.adk.model import complete
    from common.store import build_object_store

    job = json.loads(data)
    text = complete(job["user"], max_tokens=int(job["max_tokens"]), cache_prefix=job.get("system"))
    build_object_store().blob(job["result_blob"]).upload_from_string(text or "")
    log.info("worker: wrote %s (%d chars)", job["result_blob"], len(text or ""))


async def worker_scenarios(
    plan: TestPlan, plan_pack, test_data: list[TestData], *, batches: list[list[str] | None],
    now: str = "", reflections: list[str] | None = None, max_tokens: int, run: str,
) -> list[TestScenario] | None:
    """COORDINATOR side: publish one job per batch, poll GCS for the results, merge into scenarios.
    Returns None on total failure (→ caller falls back to synchronous generation); a batch whose result
    never arrives / is invalid degrades to the heuristic for its units alone."""
    ctx = plan.context_id
    summary = plan_pack.summary_text()
    system = pack_block(summary)
    jobs = []
    for i, ids in enumerate(batches):
        user = scenarios_prompt(plan, summary, test_data, reflections, include_context=False,
                                focus_units=ids)
        jobs.append((i, build_job(result_blob(ctx, run, i), system=system, user=user, max_tokens=max_tokens)))
    try:
        await asyncio.to_thread(_publish, [j for _, j in jobs])
    except Exception as exc:  # noqa: BLE001 — no topic/creds → fall back to synchronous generation
        log.warning("worker publish failed (%s) — falling back to synchronous generation", exc)
        return None

    budget = _DEFAULT_BUDGET_S
    try:
        budget = max(30.0, float(os.environ.get("TPD_WORKER_BUDGET_S", _DEFAULT_BUDGET_S)))
    except (ValueError, TypeError):
        pass
    texts = await asyncio.to_thread(_poll_results, ctx, run, [i for i, _ in jobs], budget)

    from test_plan_definition.implement.generate.scenarios import heuristic_scenarios
    merged: list[TestScenario] = []
    seen: set[str] = set()
    got = 0
    for i, ids in enumerate(batches):
        scs: list[TestScenario] | None = None
        text = texts.get(i)
        if text and isinstance(data := loads_obj(text), dict):
            scs = Scenarios(**data).to_scenarios(plan, now) or None
        if scs:
            got += 1
        else:
            log.warning("worker batch %s missing/invalid; heuristic fallback for its units", i)
            scs = heuristic_scenarios(plan, plan_pack, test_data, now=now,
                                      only_ids=set(ids) if ids else None)
        for s in scs:
            if s.id not in seen:
                seen.add(s.id)
                merged.append(s)
    if got == 0:
        return None  # nothing came back from any worker → let the caller use the synchronous path
    log.info("workers: %d/%d batches returned → %d scenarios", got, len(batches), len(merged))
    return merged or None


def _topic_path(publisher) -> str:
    project = (os.environ.get("PUBSUB_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")
               or os.environ["VERTEX_PROJECT"])  # emulator/local sets PUBSUB_PROJECT; prod has VERTEX_PROJECT
    topic = os.environ.get("TPD_WORKER_TOPIC", "tpd-gen-batches")
    return publisher.topic_path(project, topic)


def _publish(jobs: list[dict]) -> None:
    """Blocking publish of every job to the queue (runs in a worker thread). Redis Streams when
    ``TPD_QUEUE_BACKEND=redis`` (local), else Pub/Sub (prod)."""
    from common.queue import queue_backend

    if queue_backend() == "redis":
        from common.queue import redis_publish

        redis_publish(jobs)
        return
    from google.cloud import pubsub_v1

    publisher = pubsub_v1.PublisherClient()
    path = _topic_path(publisher)
    futures = [publisher.publish(path, json.dumps(j).encode()) for j in jobs]
    for f in futures:
        f.result(timeout=30)  # raise if any publish failed


def _poll_results(ctx: str, run: str, batch_ids: list[int], budget_s: float) -> dict[int, str]:
    """Poll GCS for each batch's result blob until all present or the budget elapses; return {id: text}."""
    from common.store import build_object_store

    store = build_object_store()
    out: dict[int, str] = {}
    start = time.monotonic()
    pending = set(batch_ids)
    while pending and time.monotonic() - start < budget_s:
        for i in list(pending):
            blob = store.get_blob(result_blob(ctx, run, i))
            if blob is not None:
                out[i] = blob.download_as_text()
                pending.discard(i)
        if pending:
            time.sleep(5)
    if pending:
        log.warning("workers: %d/%d results still missing after %.0fs", len(pending), len(batch_ids), budget_s)
    return out
