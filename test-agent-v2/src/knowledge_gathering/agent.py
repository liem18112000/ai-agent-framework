"""KGA root agent (ADK) — a deterministic text-dispatch router (mirrors v1 executor.base)."""

from __future__ import annotations

import json

from google.adk.agents import BaseAgent

from common.adk import tools
from common.adk.events import incoming_text, text_event
from common.interrogate import present
from common.memory.factory import build_bank
from knowledge_gathering.gather import build_gather_agent
from knowledge_gathering.refine.agent import build_refine_agent, wants_refine

_READ_TOOLS = {"search-memory": tools.search_memory, "get-note": tools.get_note,
               "search-lessons": tools.search_lessons, "veto-lesson": tools.veto_lesson}


class KgaRouter(BaseAgent):
    gather: BaseAgent
    refine: BaseAgent

    async def _run_async_impl(self, ctx):
        text = incoming_text(ctx).strip()
        low = text.lower()
        if low.startswith(("get-questions", "get-understanding")):
            yield text_event(self.name, self._read_helper(text))
            return
        if low.startswith(tuple(_READ_TOOLS)):
            yield text_event(self.name, await self._read_tool(text))
            return
        state = build_bank().read_refine_state(ctx.session.id) or {}
        target = self.refine if (state and not state.get("done")) or wants_refine(text) else self.gather
        async for ev in target.run_async(ctx):
            yield ev

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
