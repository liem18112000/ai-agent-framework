"""Job queue for Phase-C distributed scenario generation — Pub/Sub (prod) or Redis Streams (local).

The coordinator publishes per-batch jobs; a worker pool consumes them, generates, writes the result to
the ObjectStore, and acks. Backend chosen by ``TPD_QUEUE_BACKEND`` (default ``pubsub``). Redis uses a
**Stream** (``XADD`` + a consumer group with ``XACK``), NOT raw pub/sub — pub/sub is lossy (no ack, no
redelivery, no persistence) and would silently drop batches. The Pub/Sub publish path stays in
``workers.py`` (its consume side is a Cloud Run HTTP push → ``worker.py``); Redis consume is a loop
(``redis_worker.py``). ``redis`` is already a dependency.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable

from common.env import env_int
from common.monitoring import get_logger

log = get_logger("queue")


def queue_backend() -> str:
    return os.environ.get("TPD_QUEUE_BACKEND", "pubsub").strip().lower()


def _stream() -> str:
    return os.environ.get("TPD_WORKER_TOPIC", "tpd-gen-batches")


def _group() -> str:
    return os.environ.get("TPD_WORKER_GROUP", "tpd-gen-workers")


def _redis():
    import redis

    return redis.Redis(host=os.environ.get("REDIS_HOST", "redis"),
                       port=env_int("REDIS_PORT", 6379), decode_responses=False)


def redis_publish(jobs: list[dict]) -> None:
    """XADD one entry per job onto the stream (each job's bytes under the ``job`` field)."""
    r = _redis()
    stream = _stream()
    for j in jobs:
        r.xadd(stream, {b"job": json.dumps(j).encode()})
    log.info("queue(redis): published %d job(s) to %s", len(jobs), stream)


def redis_consume(handler: Callable[[bytes], None]) -> None:
    """Blocking consumer loop: read from the group, run ``handler(job_bytes)``, XACK on success. A
    failing job is left unacked (stays in the group's PEL) so a restart / another consumer can reclaim
    it via XAUTOCLAIM — matching the coordinator's per-batch fallback. ponytail: no automatic
    dead-consumer reclaim (add an XAUTOCLAIM sweep if a crashed worker's batches must be re-run)."""
    r = _redis()
    stream, group = _stream(), _group()
    try:
        r.xgroup_create(stream, group, id="0", mkstream=True)
    except Exception as exc:  # BUSYGROUP: the group already exists (idempotent); re-raise anything else
        if "BUSYGROUP" not in str(exc):
            raise
    consumer = os.environ.get("HOSTNAME", "worker-1")
    log.info("queue(redis): consuming %s as %s/%s", stream, group, consumer)
    while True:
        resp = r.xreadgroup(group, consumer, {stream: ">"}, count=1, block=5000)
        for _s, entries in resp or []:
            for msg_id, fields in entries:
                data = fields.get(b"job") or b""
                try:
                    handler(data)
                    r.xack(stream, group, msg_id)
                except Exception as exc:  # noqa: BLE001 — leave unacked → reclaimable; don't crash the loop
                    log.warning("queue(redis): job %s failed (%s) — left unacked", msg_id, exc)
