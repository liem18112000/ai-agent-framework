"""ApproveAgent — the autonomous approve step of the Testing-Agent pipeline.

Confirms the plan with no human gate (the opt-in autonomous path): marks the plan CONFIRMED and
closes the define session. Keys on `ctx.session.id` (the shared SequentialAgent session).
"""

from __future__ import annotations

from google.adk.agents import BaseAgent

from common.adk.events import text_event
from common.memory.factory import build_bank
from test_plan_definition import memory as store
from test_plan_definition.models import CONFIRMED


class ApproveAgent(BaseAgent):
    async def _run_async_impl(self, ctx):
        bank, ctx_id = build_bank(), ctx.session.id
        plan = store.read_plan(bank, ctx_id)
        if plan and plan.status != CONFIRMED:
            plan.status = CONFIRMED
            store.write_plan(bank, plan)
        store.write_plan_state(bank, ctx_id, {"done": True})
        yield text_event(self.name, "[auto-approve] plan confirmed")
