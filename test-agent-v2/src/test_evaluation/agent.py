"""Test-Evaluation ADK agent (E1) — scores a pack/plan by context id and returns the report."""

from __future__ import annotations

import asyncio

from common.adk.router import RouterAgent
from common.memory.factory import build_bank
from test_evaluation.engine import evaluate_pack
from test_evaluation.golden import golden_for, golden_plan_for
from test_evaluation.ops import _is_plan, extract_ctx, render, render_plan
from test_evaluation.plan_engine import evaluate_plan


class EvaluatorAgent(RouterAgent):
    async def _run_async_impl(self, ctx):
        text = self.read(ctx)
        ctx_id = extract_ctx(text) or ctx.session.id
        bank = build_bank()
        if _is_plan(text):
            report = await asyncio.to_thread(evaluate_plan, bank, ctx_id, golden_plan_for(ctx_id))
            yield self.reply(render_plan(report))
            return
        report = await asyncio.to_thread(evaluate_pack, bank, ctx_id, golden_for(ctx_id))
        yield self.reply(render(report))


def build_root_agent() -> EvaluatorAgent:
    return EvaluatorAgent(name="test_evaluation")


root_agent = build_root_agent()
