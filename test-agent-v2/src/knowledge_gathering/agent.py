"""KGA root agent (ADK) — a deterministic text-dispatch router (mirrors v1 executor.base)."""

from __future__ import annotations

import asyncio
import json

from common.adk import tools
from common.adk.router import Agent, RouterAgent
from common.interrogate import present
from common.memory.factory import build_bank
from knowledge_gathering.gather import build_gather_agent
from knowledge_gathering.monitoring import get_logger
from knowledge_gathering.refine.agent import build_refine_agent, wants_refine

log = get_logger("adk.router")

_READ_TOOLS = {"search-memory": tools.search_memory, "get-note": tools.get_note,
               "search-lessons": tools.search_lessons, "veto-lesson": tools.veto_lesson}


class KgaRouter(RouterAgent):
    gather: Agent
    refine: Agent

    async def _run_async_impl(self, ctx):
        text = self.read(ctx).strip()
        low = text.lower()
        if low.startswith(("get-questions", "get-understanding")):
            yield self.reply(self._read_helper(text))
            return
        if low.startswith(tuple(_READ_TOOLS)):
            yield self.reply(await self._read_tool(text))
            return
        state = await self._refine_state(ctx.session.id)
        target = self.refine if (state and not state.get("done")) or wants_refine(text) else self.gather
        async for ev in target.run_async(ctx):
            yield ev

    async def _refine_state(self, session_id) -> dict:
        """Read the session's refine state OFF the event loop (sync GCS), degrading to {} on any error
        so a transient memory hiccup can't crash routing."""
        try:
            return await asyncio.to_thread(lambda: build_bank().read_refine_state(session_id)) or {}
        except Exception as exc:  # noqa: BLE001 — routing must survive a memory read failure
            log.warning("A2A router: refine-state read failed (%s)", exc)
            return {}

    def _read_helper(self, text: str) -> str:
        ctx_id = present.extract_ctx(text, ("get-questions", "get-understanding"))
        if not ctx_id:
            return "Provide a context id."
        bank = build_bank()
        if text.lower().startswith("get-understanding"):
            return bank.read_understanding(ctx_id) or f"No understanding yet for {ctx_id}."
        qs = bank.read_questions(ctx_id)
        if not qs:
            return f"No questions yet for {ctx_id}."
        return json.dumps([{"id": q.id, "round": q.round, "question": q.question, "status": q.status}
                           for q in qs], indent=1)

    async def _read_tool(self, text: str) -> str:
        cmd, _, arg = text.partition(" ")
        fn = _READ_TOOLS.get(cmd.lower())
        return await fn(arg.strip()) if fn else "Unknown command."


def build_root_agent() -> KgaRouter:
    gather, refine = build_gather_agent(), build_refine_agent()
    return KgaRouter(name="knowledge_gathering", gather=gather, refine=refine,
                     sub_agents=[gather, refine])


root_agent = build_root_agent()
