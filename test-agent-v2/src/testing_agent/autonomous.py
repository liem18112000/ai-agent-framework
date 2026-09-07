"""Headless sub-agents for the autonomous pipeline (E7).

The gated path pauses for a human at each round; the autonomous path instead **auto-answers with the
agent's own recommendations** (`accept_recommendation`) and runs each interrogation to completion.
These wrap the reused headless drivers (`interrogate.refine`, `define.define`) — determinism + B0–B6
unchanged. All steps key on `ctx.session.id` (the SequentialAgent shares one session), so gather's
pack, refine's understanding, define's plan, and implement all line up under one context id.
"""

from __future__ import annotations

from google.adk.agents import BaseAgent

from common.adk.events import text_event
from common.interrogate.loop import accept_recommendation, refine
from common.memory.factory import build_bank
from test_plan_definition import memory as store
from test_plan_definition.define.loop import define
from test_plan_definition.models import CONFIRMED


class RefineAutoAgent(BaseAgent):
    async def _run_async_impl(self, ctx):
        result = await refine(build_bank(), ctx.session.id, answer_fn=accept_recommendation)
        n = len(getattr(result, "insights", []) or [])
        yield text_event(self.name, f"[auto-refine] confidence={getattr(result, 'confidence', '')}, {n} insights")


class DefineAutoAgent(BaseAgent):
    async def _run_async_impl(self, ctx):
        result = await define(build_bank(), ctx.session.id, answer_fn=accept_recommendation)
        yield text_event(self.name, f"[auto-define] confidence={getattr(result, 'confidence', '')}")


class AutoApproveAgent(BaseAgent):
    async def _run_async_impl(self, ctx):
        bank, ctx_id = build_bank(), ctx.session.id
        plan = store.read_plan(bank, ctx_id)
        if plan and plan.status != CONFIRMED:
            plan.status = CONFIRMED
            store.write_plan(bank, plan)
        store.write_plan_state(bank, ctx_id, {"done": True})
        yield text_event(self.name, "[auto-approve] plan confirmed")
