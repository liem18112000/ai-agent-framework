"""Test-Evaluation ADK agent (E1) — scores a pack/plan by context id, or benchmarks runs."""

from __future__ import annotations

import asyncio

from common.adk.router import RouterAgent
from common.memory.factory import build_bank
from test_evaluation.benchmark import benchmark_run, compare, summarize
from test_evaluation.engine import evaluate_pack, evaluate_plan
from test_evaluation.golden import golden_for, golden_plan_for
from test_evaluation.ops import _is_plan, extract_ctx, render, render_plan


class EvaluatorAgent(RouterAgent):
    async def _run_async_impl(self, ctx):
        text = self.read(ctx)
        bank = build_bank()
        parts = text.replace(",", " ").split()
        verb = parts[0].lower() if parts else ""
        # Benchmark verbs first (none contain the word "plan", so they never hit the pack/plan sniff).
        if verb == "benchmark":
            ctx_id = parts[1] if len(parts) > 1 else ctx.session.id
            yield self.reply(await asyncio.to_thread(benchmark_run, bank, ctx_id))
            return
        if verb == "compare-benchmarks":
            yield self.reply(await asyncio.to_thread(compare, bank, parts[1:]))
            return
        if verb == "summarize-benchmarks":
            k = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 5
            yield self.reply(await asyncio.to_thread(summarize, bank, k))
            return
        ctx_id = extract_ctx(text) or ctx.session.id
        if _is_plan(text):
            report = await asyncio.to_thread(evaluate_plan, bank, ctx_id, golden_plan_for(ctx_id))
            yield self.reply(render_plan(report))
            return
        report = await asyncio.to_thread(evaluate_pack, bank, ctx_id, golden_for(ctx_id))
        yield self.reply(render(report))


def build_root_agent() -> EvaluatorAgent:
    return EvaluatorAgent(name="test_evaluation")


root_agent = build_root_agent()
