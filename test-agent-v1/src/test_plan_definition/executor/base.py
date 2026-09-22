"""The A2A executor — dispatches Define (multi-turn) vs Implement (one-shot).

Routing mirrors knowledge_gathering.executor.base: read helpers (get-test-plan /
get-scenarios) first, then a live define session or a define request, then implement,
else a help reply. A live session is what catches a bare-answer continuation turn (whose
text has no `define` prefix). Dependencies are injectable for tests.
"""

from __future__ import annotations

import asyncio

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue

from common import learn
from test_plan_definition.executor.common import build_bank, now, reply
from test_plan_definition.executor.define import (
    live_session,
    run_approve,
    run_define,
    run_read_helper,
    wants_define,
)
from test_plan_definition.executor.implement import run_implement


class TestPlanDefinitionExecutor(AgentExecutor):
    def __init__(self, *, bank=None, generator=None, restater=None) -> None:
        self._bank = bank
        self._generator, self._restater = generator, restater

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        text = (context.get_user_input() or "").strip()
        a2a_ctx = context.context_id or ""

        try:
            bank = self._bank or build_bank()
        except Exception:  # noqa: BLE001 — bank is optional for the help/config-error path
            bank = None

        # L5: flush pending self-learning captures at the head of ANY request (off the enqueuing
        # request's own path) so a lesson is persisted by the next call, whatever its type.
        if bank is not None and learn.capture_enabled("TPD"):
            await asyncio.to_thread(learn.drain, bank, now=now())

        # M2: project notes/insights into the pgvector index (no-op under MEMORY_BACKEND=gcs).
        from common.memory.pg.project import maybe_drain_index
        await maybe_drain_index(bank)

        if text.lower().startswith(("get-test-plan", "get-scenarios")):
            if bank is None:
                return await reply(context, event_queue, "Config error: memory bank unavailable.")
            return await run_read_helper(self, context, event_queue, bank, text)

        if text.lower().startswith("approve"):  # explicit gate — wins over a live define session
            if bank is None:
                return await reply(context, event_queue, "Config error: memory bank unavailable.")
            return await run_approve(self, context, event_queue, bank, text, a2a_ctx)

        if (bank and live_session(bank, a2a_ctx)) or wants_define(text):
            if bank is None:
                return await reply(context, event_queue, "Config error: memory bank unavailable.")
            return await run_define(self, context, event_queue, bank, text, a2a_ctx)

        if text.lower().startswith("implement"):
            if bank is None:
                return await reply(context, event_queue, "Config error: memory bank unavailable.")
            return await run_implement(self, context, event_queue, bank, text, a2a_ctx)

        return await reply(
            context, event_queue,
            "test-plan-definition agent. Try: 'define <context_id>' (methodology/scope/metrics), "
            "then 'implement <context_id>'. context_id comes from knowledge_gathering's approve.",
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("cancel is not supported yet")
