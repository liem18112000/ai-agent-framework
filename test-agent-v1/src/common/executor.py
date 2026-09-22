"""Shared A2A executor helpers — timestamps, a plain message reply, and the GCS bank.

Package-agnostic, so both agents reuse them. `build_bank` gives both the same memory
bank (same GCS_BUCKET). Agent-specific builders (e.g. the Atlassian client) live in
each agent's own package, not here.
"""

from __future__ import annotations

import datetime

from a2a.server.agent_execution import RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import a2a_pb2


def now() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H-%M-%SZ")


async def reply(context: RequestContext, event_queue: EventQueue, text: str) -> None:
    """Enqueue a plain agent Message (no task-status transition)."""
    updater = TaskUpdater(event_queue, context.task_id, context.context_id)
    await event_queue.enqueue_event(updater.new_agent_message([a2a_pb2.Part(text=text)]))


def build_bank():
    """The GCS memory bank from env (GCS_BUCKET, optional GCP_PROJECT/VERTEX_PROJECT)."""
    import os

    from google.cloud import storage

    from common.memory import MemoryBank
    from common.memory.pg.project import index_on_write

    client = storage.Client(project=os.environ.get("GCP_PROJECT") or os.environ.get("VERTEX_PROJECT"))
    # on_write enqueues an index-projection job; index_on_write is a no-op under MEMORY_BACKEND=gcs,
    # so this is safe to wire unconditionally and a runtime backend flip needs no bank rebuild.
    return MemoryBank(client.bucket(os.environ["GCS_BUCKET"]), on_write=index_on_write)
