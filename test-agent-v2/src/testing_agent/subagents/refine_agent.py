"""RefineAgent — the autonomous refine step of the Testing-Agent pipeline.

Auto-answers each interrogation round with the agent's own recommendations
(`accept_recommendation`) — the opt-in autonomous path (no human gate). Wraps the reused headless
`interrogate.refine` driver; determinism + B0–B6 unchanged. Keys on `ctx.session.id` (the shared
SequentialAgent session), so it lines up with gather's pack under one context id.
"""

from __future__ import annotations

from google.adk.agents import BaseAgent

from common.adk.events import text_event
from common.interrogate.loop import accept_recommendation, refine
from common.memory.factory import build_bank


class RefineAgent(BaseAgent):
    async def _run_async_impl(self, ctx):
        result = await refine(build_bank(), ctx.session.id, answer_fn=accept_recommendation)
        n = len(getattr(result, "insights", []) or [])
        yield text_event(self.name, f"[auto-refine] confidence={getattr(result, 'confidence', '')}, {n} insights")
