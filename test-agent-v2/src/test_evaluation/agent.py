"""Test-Evaluation ADK agent (E1) — scores a pack/plan by context id and returns the report.

A thin custom BaseAgent over the reused engine (`engine.evaluate_pack` / `plan_engine.evaluate_plan`)
so `test_evaluation` is `adk web`/`adk run`-discoverable like the other agents. The canonical
`adk eval` harness (domain metrics as ADK custom metrics) lives in `test_evaluation.eval` (Plan B/E5).
Read-only; keys on the context id (from the message, else the session id).
"""

from __future__ import annotations

import asyncio

from google.adk.agents import BaseAgent

from common.adk.events import incoming_text, text_event
from common.memory.factory import build_bank
from test_evaluation.executor.base import (
    _is_plan,
    evaluate_pack,
    evaluate_plan,
    extract_ctx,
    golden_for,
    golden_plan_for,
    render,
    render_plan,
)


class EvaluatorAgent(BaseAgent):
    async def _run_async_impl(self, ctx):
        text = incoming_text(ctx)
        ctx_id = extract_ctx(text) or ctx.session.id
        bank = build_bank()
        if _is_plan(text):
            report = await asyncio.to_thread(evaluate_plan, bank, ctx_id, golden_plan_for(ctx_id))
            yield text_event(self.name, render_plan(report))
            return
        report = await asyncio.to_thread(evaluate_pack, bank, ctx_id, golden_for(ctx_id))
        yield text_event(self.name, render(report))


def build_root_agent() -> EvaluatorAgent:
    return EvaluatorAgent(name="test_evaluation")


root_agent = build_root_agent()
