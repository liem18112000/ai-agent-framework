"""Shared A2A executor helpers — timestamps, a plain message reply, and the GCS bank."""

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


from common.memory.factory import build_bank  # noqa: F401
