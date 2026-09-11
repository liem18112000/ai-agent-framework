"""TPD root agent (ADK) — a deterministic text-dispatch router (mirrors v1 executor.base)."""

from __future__ import annotations

import asyncio

from google.adk.agents import BaseAgent

from common.adk.events import incoming_text, text_event
from common.interrogate import present
from common.memory.factory import build_bank
from common.testplan import memory as store
from common.testplan.models import CONFIRMED
from test_plan_definition.define.agent import wants_define


class TpdRouter(BaseAgent):
    define: BaseAgent
    implement: BaseAgent

    async def _run_async_impl(self, ctx):
        text = incoming_text(ctx).strip()
        low = text.lower()
        if low.startswith(("get-test-plan", "get-scenarios", "get-coverage")):
            yield text_event(self.name, await asyncio.to_thread(self._read_helper, text))
            return
        if low.startswith("approve"):
            yield text_event(self.name, await asyncio.to_thread(self._approve, ctx, text))
            return
        impl_st, plan_st = await asyncio.to_thread(self._states, ctx.session.id)
        if impl_st and not impl_st.get("done"):  # interactive implement interrogation is live
            async for ev in self.implement.run_async(ctx):
                yield ev
        elif (plan_st and not plan_st.get("done")) or wants_define(text):
            async for ev in self.define.run_async(ctx):
                yield ev
        elif low.startswith("implement"):
            async for ev in self.implement.run_async(ctx):
                yield ev
        else:
            yield text_event(self.name, "Provide: define <ctx> | approve <ctx> | implement <ctx> | "
                                        "get-test-plan <ctx> | get-scenarios <ctx>.")

    def _states(self, ctx_id: str) -> tuple[dict, dict]:
        """Implement + plan state (sync GCS) — run off the loop; degrade to empty so a transient
        memory read can't crash routing."""
        try:
            bank = build_bank()
            return (store.read_implement_state(bank, ctx_id) or {},
                    store.read_plan_state(bank, ctx_id) or {})
        except Exception:  # noqa: BLE001 — routing survives a memory read failure
            return {}, {}

    def _read_helper(self, text: str) -> str:
        ctx_id = present.extract_ctx(text, ("get-test-plan", "get-scenarios", "get-coverage"))
        if not ctx_id:
            return "Provide a context id."
        bank = build_bank()
        low = text.lower()
        if low.startswith("get-test-plan"):
            return store.read_plan_brief(bank, ctx_id) or f"No test plan yet for {ctx_id}."
        if low.startswith("get-coverage"):
            return store.read_coverage_md(bank, ctx_id) or \
                f"No coverage matrix yet for {ctx_id} — run implement first."
        return store.read_scenarios_md(bank, ctx_id) or f"No scenarios yet for {ctx_id} — run implement first."

    def _approve(self, ctx, text: str) -> str:
        ctx_id = present.extract_ctx(text, ("approve",)) or ctx.session.id
        bank = build_bank()
        plan = store.read_plan(bank, ctx_id)
        if plan is None:
            return f"No test plan to approve for {ctx_id}; run define first."
        if plan.status != CONFIRMED:
            plan.status = CONFIRMED
            store.write_plan(bank, plan)
        store.write_plan_state(bank, ctx_id, {"done": True})
        brief = store.read_plan_brief(bank, ctx_id) or ""
        return f"APPROVED {ctx_id} (status: confirmed)\n\n{brief}"


def build_root_agent() -> TpdRouter:
    from test_plan_definition.define.agent import build_define_agent
    from test_plan_definition.implement.agent import build_implement_agent
    define, implement = build_define_agent(), build_implement_agent(name="implement")
    return TpdRouter(name="test_plan_definition", define=define, implement=implement,
                     sub_agents=[define, implement])


root_agent = build_root_agent()
