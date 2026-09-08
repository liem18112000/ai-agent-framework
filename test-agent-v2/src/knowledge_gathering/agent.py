"""KGA root agent (ADK) — a deterministic text-dispatch router (mirrors v1 executor.base).

Routes by message text, exactly like v1: read helpers → memory/lesson tools → live/started refine →
gather. The LLM does NOT choose the branch (invariant I1). Read commands run inline (deterministic);
gather/refine delegate to the sub-agents. Head-of-request drain/recall are the Runner plugins (§6).

This is the canonical `agent.py:root_agent` (adk web/run discoverable). The v1 A2A card + skills now
live in `a2a_card.py` (still used by the copied a2a shells + `adk_app`/`serve` for exact skill
parity, invariant I4).
"""

from __future__ import annotations

import json

from google.adk.agents import BaseAgent

from common.adk import tools
from common.adk.events import incoming_text, text_event
from common.interrogate import present
from common.memory.factory import build_bank
from knowledge_gathering.refine import wants_refine


class KgaRouter(BaseAgent):
    gather: BaseAgent
    refine: BaseAgent

    async def _run_async_impl(self, ctx):
        text = incoming_text(ctx).strip()
        low = text.lower()

        if low.startswith(("get-questions", "get-understanding")):
            yield text_event(self.name, self._read_helper(text))
            return
        if low.startswith(("search-memory", "get-note", "search-lessons", "veto-lesson")):
            yield text_event(self.name, await self._read_tool(text))
            return

        bank = build_bank()
        state = bank.read_refine_state(ctx.session.id) or {}
        live = bool(state) and not state.get("done")
        if live or wants_refine(text):
            async for ev in self.refine.run_async(ctx):
                yield ev
            return
        async for ev in self.gather.run_async(ctx):
            yield ev

    # --- deterministic read commands (no sub-agent, no LLM) --- #
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
        return json.dumps(
            [{"id": q.id, "round": q.round, "question": q.question, "status": q.status} for q in qs],
            indent=1,
        )

    async def _read_tool(self, text: str) -> str:
        cmd, _, arg = text.partition(" ")
        arg = arg.strip()
        fn = {
            "search-memory": tools.search_memory,
            "get-note": tools.get_note,
            "search-lessons": tools.search_lessons,
            "veto-lesson": tools.veto_lesson,
        }.get(cmd.lower())
        return await fn(arg) if fn else "Unknown command."


def build_root_agent() -> KgaRouter:
    from knowledge_gathering.agents.gather_agent import GatherAgent
    from knowledge_gathering.agents.refine_agent import build_refine_agent

    gather = GatherAgent(name="gather")
    refine = build_refine_agent()
    return KgaRouter(name="knowledge_gathering", gather=gather, refine=refine, sub_agents=[gather, refine])


root_agent = build_root_agent()
