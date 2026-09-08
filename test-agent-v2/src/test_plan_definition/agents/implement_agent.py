"""ImplementAgent — TPD's one-shot artifact generation as a custom ADK BaseAgent."""

from __future__ import annotations

import datetime

from google.adk.agents import BaseAgent

from common.adk.events import incoming_text, text_event
from common.memory.factory import build_bank
from test_plan_definition.implement.generate import implement_plan
from test_plan_definition.implement_ops import _capture_implement, summarize_implement


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H-%M-%SZ")


class ImplementAgent(BaseAgent):
    async def _run_async_impl(self, ctx):
        text = incoming_text(ctx)
        ctx_id = ctx.session.id
        detail = "detail" in text.lower().split()
        bank = build_bank()
        result = await implement_plan(
            bank, ctx_id, run_id=f"impl-{ctx_id[:8]}", now=_now(), detail=detail)
        _capture_implement(bank, ctx_id, result)
        if not result.scenarios:
            yield text_event(self.name, result.message or f"Nothing generated for {ctx_id}.")
            return
        yield text_event(self.name, summarize_implement(result))
