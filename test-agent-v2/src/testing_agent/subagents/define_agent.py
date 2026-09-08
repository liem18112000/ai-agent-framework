"""DefineAgent — the autonomous define step of the Testing-Agent pipeline."""

from __future__ import annotations

from google.adk.agents import BaseAgent

from common.adk.events import text_event
from common.interrogate.loop import accept_recommendation
from common.memory.factory import build_bank
from test_plan_definition.define.loop import define


class DefineAgent(BaseAgent):
    async def _run_async_impl(self, ctx):
        result = await define(build_bank(), ctx.session.id, answer_fn=accept_recommendation)
        yield text_event(self.name, f"[auto-define] confidence={getattr(result, 'confidence', '')}")
