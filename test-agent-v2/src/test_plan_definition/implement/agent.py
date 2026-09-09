"""ImplementAgent — TPD's one-shot artifact generation (custom ADK BaseAgent), plus the lesson
capture and reply summary."""

from __future__ import annotations

import datetime
from dataclasses import asdict

from google.adk.agents import BaseAgent

from common import learn
from common.adk.events import incoming_text, text_event
from common.memory.factory import build_bank
from common.testplan.models import HAPPY, NEGATIVE
from test_plan_definition.implement.generate import ImplementResult, implement_plan
from test_plan_definition.monitoring import get_logger

log = get_logger("tpd.implement")


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H-%M-%SZ")


def _capture_implement(bank, context_id: str, result: ImplementResult) -> None:
    if not learn.capture_enabled("TPD"):
        return
    try:
        sigs = learn.from_implement(result.scenarios, context_id=context_id)
        if sigs:
            learn.enqueue(bank, learn.CaptureJob(
                id=f"cap-implement-{context_id}", context_id=context_id, step="implement",
                signals=[asdict(s) for s in sigs]))
    except Exception as exc:  # noqa: BLE001 — capture must not break implement
        log.warning("implement: lesson capture skipped (%s)", exc)


def summarize_implement(result: ImplementResult) -> str:
    happy = sum(s.kind == HAPPY for s in result.scenarios)
    negative = sum(s.kind == NEGATIVE for s in result.scenarios)
    titles = "\n".join(f"- [{s.kind}] {s.title}" for s in result.scenarios)
    feature = "  Exported a BDD .feature.\n" if result.feature else ""
    return (f"Implement complete: {len(result.test_data)} test-data, {len(result.scenarios)} "
            f"scenarios ({happy} happy / {negative} negative), {len(result.steps)} steps.\n{feature}\n"
            f"{titles}")


class ImplementAgent(BaseAgent):
    async def _run_async_impl(self, ctx):
        ctx_id = ctx.session.id
        detail = "detail" in incoming_text(ctx).lower().split()
        bank = build_bank()
        result = await implement_plan(bank, ctx_id, run_id=f"impl-{ctx_id[:8]}", now=_now(),
                                      detail=detail)
        _capture_implement(bank, ctx_id, result)
        if not result.scenarios:
            yield text_event(self.name, result.message or f"Nothing generated for {ctx_id}.")
            return
        yield text_event(self.name, summarize_implement(result))
