"""TPD root agent (ADK) — a deterministic text-dispatch router (mirrors v1 executor.base).

Order (like v1): reads → approve (wins over a live define) → live/started define → implement → help.
The LLM never chooses the branch (I1). Reads + approve run inline (deterministic); define/implement
delegate to sub-agents.
"""

from __future__ import annotations

from google.adk.agents import BaseAgent

from common.adk.events import incoming_text, text_event
from common.interrogate import present
from common.memory.factory import build_bank
from test_plan_definition import memory as store
from test_plan_definition.executor.define import wants_define
from test_plan_definition.models import CONFIRMED


class TpdRouter(BaseAgent):
    define: BaseAgent
    implement: BaseAgent

    async def _run_async_impl(self, ctx):
        text = incoming_text(ctx).strip()
        low = text.lower()

        if low.startswith(("get-test-plan", "get-scenarios")):
            yield text_event(self.name, self._read_helper(text))
            return
        if low.startswith("approve"):
            yield text_event(self.name, self._approve(ctx, text))
            return

        bank = build_bank()
        st = store.read_plan_state(bank, ctx.session.id) or {}
        live = bool(st) and not st.get("done")
        if live or wants_define(text):
            async for ev in self.define.run_async(ctx):
                yield ev
            return
        if low.startswith("implement"):
            async for ev in self.implement.run_async(ctx):
                yield ev
            return
        yield text_event(self.name, "Provide: define <ctx> | approve <ctx> | implement <ctx> | "
                                    "get-test-plan <ctx> | get-scenarios <ctx>.")

    # --- deterministic inline commands (no sub-agent, no LLM) --- #
    def _ctx(self, text: str, ctx) -> str:
        return present.extract_ctx(text, ("define", "approve", "implement", "get-test-plan",
                                          "get-scenarios")) or ctx.session.id

    def _read_helper(self, text: str) -> str:
        ctx_id = present.extract_ctx(text, ("get-test-plan", "get-scenarios"))
        if not ctx_id:
            return "Provide a context id."
        bank = build_bank()
        if text.lower().startswith("get-test-plan"):
            return store.read_plan_brief(bank, ctx_id) or f"No test plan yet for {ctx_id}."
        return store.read_scenarios_md(bank, ctx_id) or f"No scenarios yet for {ctx_id} — run implement first."

    def _approve(self, ctx, text: str) -> str:
        ctx_id = self._ctx(text, ctx)
        bank = build_bank()
        plan = store.read_plan(bank, ctx_id)
        if plan is None:
            return f"No test plan to approve for {ctx_id}; run define first."
        if plan.status != CONFIRMED:
            plan.status = CONFIRMED
            store.write_plan(bank, plan)
        store.write_plan_state(bank, ctx_id, {"done": True})  # close any lingering define session
        brief = store.read_plan_brief(bank, ctx_id) or ""
        return f"APPROVED {ctx_id} (status: confirmed)\n\n{brief}"


def build_root_agent() -> TpdRouter:
    from test_plan_definition.agents.define_agent import build_define_agent
    from test_plan_definition.agents.implement_agent import ImplementAgent

    define = build_define_agent()
    implement = ImplementAgent(name="implement")
    # ADK agent names must be valid Python identifiers; card name stays "test-plan-definition".
    return TpdRouter(name="test_plan_definition", define=define, implement=implement,
                     sub_agents=[define, implement])


root_agent = build_root_agent()
