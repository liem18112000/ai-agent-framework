"""Redis Streams consumer worker (Phase C, local) — the alternative to the Pub/Sub push worker.

Runs its OWN process (direct ``complete()`` path, no ADK Runner), loops on the job stream, generates,
writes the result to the ObjectStore, and acks. Served plainly: ``python redis_worker.py``. Used when
``TPD_QUEUE_BACKEND=redis`` (the local docker-compose default); the Pub/Sub push worker is ``worker.py``.
"""

from __future__ import annotations

from common.monitoring import get_logger
from common.queue import redis_consume
from test_plan_definition.implement.generate.workers import handle_job

if __name__ == "__main__":
    get_logger("redis_worker").info("redis worker: starting consumer")
    redis_consume(handle_job)  # blocking
