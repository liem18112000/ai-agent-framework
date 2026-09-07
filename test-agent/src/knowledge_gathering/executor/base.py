"""The A2A executor — dispatches Gather (one-shot) vs Refine (multi-turn).

Routing: a live refine session or a `refine`/context_id request → Refine; `get-questions`/
`get-understanding` → read helpers; everything else → Gather. Dependencies are injectable for tests.
"""

from __future__ import annotations

import asyncio

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue

from common import learn
from knowledge_gathering.executor.common import build_bank, now, reply
from knowledge_gathering.executor.gather import run_gather
from knowledge_gathering.executor.memory import (
    run_get_note,
    run_search_lessons,
    run_search_memory,
    run_veto_lesson,
)
from knowledge_gathering.executor.refine import (
    live_session,
    run_read_helper,
    run_refine,
    wants_refine,
)


class KnowledgeGatheringExecutor(AgentExecutor):
    def __init__(self, *, client=None, bank=None, distiller=None,
                 generator=None, understander=None, gatherer=None) -> None:
        self._client, self._bank, self._distiller = client, bank, distiller
        self._generator, self._understander, self._gatherer = generator, understander, gatherer

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        text = (context.get_user_input() or "").strip()
        a2a_ctx = context.context_id or ""

        try:
            bank = self._bank or build_bank()
        except Exception:  # noqa: BLE001 — bank is optional for the gather config-error path
            bank = None

        # L5: flush pending self-learning captures at the head of ANY request (off the enqueuing
        # request's own path) so a lesson is persisted by the next call, whatever its type.
        if bank is not None and learn.capture_enabled("KGA"):
            await asyncio.to_thread(learn.drain, bank, now=now())

        if text.lower().startswith(("get-questions", "get-understanding")) and bank is not None:
            return await run_read_helper(self, context, event_queue, bank, text)

        if text.lower().startswith(("search-lessons", "veto-lesson")):  # L5 governance
            if bank is None:
                return await reply(context, event_queue, "Config error: memory bank unavailable.")
            if text.lower().startswith("search-lessons"):
                return await run_search_lessons(self, context, event_queue, bank, text)
            return await run_veto_lesson(self, context, event_queue, bank, text)

        if text.lower().startswith(("search-memory", "get-note")):
            if bank is None:
                return await reply(context, event_queue, "Config error: memory bank unavailable.")
            if text.lower().startswith("search-memory"):
                return await run_search_memory(self, context, event_queue, bank, text)
            return await run_get_note(self, context, event_queue, bank, text)

        if (bank and live_session(bank, a2a_ctx)) or wants_refine(text):
            if bank is None:
                return await reply(context, event_queue, "Config error: memory bank unavailable.")
            return await run_refine(self, context, event_queue, bank, text, a2a_ctx)

        return await run_gather(self, context, event_queue, text)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("cancel is not supported yet")
