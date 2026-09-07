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


# build_bank was lifted to the framework-neutral common.memory.factory (ADK-transform mapping row 5b);
# re-exported here so the legacy a2a shells (`from common.executor import build_bank`) keep working.
from common.memory.factory import build_bank  # noqa: F401
