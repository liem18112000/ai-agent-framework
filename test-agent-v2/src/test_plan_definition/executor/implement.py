"""Test Plan implement (Stage B) handler — one-shot artifact generation over A2A."""

from __future__ import annotations

import asyncio
from dataclasses import asdict

from a2a.server.agent_execution import RequestContext
from a2a.server.events import EventQueue

from common import learn
from test_plan_definition.executor.common import now, reply
from test_plan_definition.executor.define import extract_ctx
from test_plan_definition.implement.generate import ImplementResult, implement_plan
from test_plan_definition.models import HAPPY, NEGATIVE
from test_plan_definition.monitoring import get_logger

log = get_logger("executor.implement")


def _capture_implement(bank, context_id: str, result: ImplementResult) -> None:
    """L3: enqueue ONE async coverage-summary lesson from an implement (not the scenarios)."""
    if not learn.capture_enabled("TPD"):
        return
    try:
        sigs = learn.from_implement(result.scenarios, context_id=context_id)
        if sigs:
            learn.enqueue(bank, learn.CaptureJob(
                id=f"cap-implement-{context_id}", context_id=context_id, step="implement",
                signals=[asdict(s) for s in sigs]))
    except Exception as exc:  # noqa: BLE001 — capture must not break implement
        log.warning("A2A implement: lesson capture skipped (%s)", exc)


def summarize_implement(result: ImplementResult) -> str:
    happy = sum(s.kind == HAPPY for s in result.scenarios)
    negative = sum(s.kind == NEGATIVE for s in result.scenarios)
    titles = "\n".join(f"- [{s.kind}] {s.title}" for s in result.scenarios)
    feature = "  Exported a BDD .feature.\n" if result.feature else ""
    return (
        f"Implement complete: {len(result.test_data)} test-data, {len(result.scenarios)} "
        f"scenarios ({happy} happy / {negative} negative), {len(result.steps)} steps.\n{feature}\n"
        f"{titles}"
    )


async def run_implement(ex, context: RequestContext, event_queue: EventQueue,
                        bank, text: str, a2a_ctx: str) -> None:
    ctx = extract_ctx(text) or a2a_ctx
    if not ctx:
        return await reply(context, event_queue, "Provide a context id, e.g. 'implement run-6f2a'.")
    detail = "detail" in text.lower().split()
    result = await asyncio.to_thread(
        implement_plan, bank, ctx, run_id=f"impl-{(a2a_ctx or ctx)[:8]}", now=now(), detail=detail
    )
    _capture_implement(bank, ctx, result)
    if not result.scenarios:
        return await reply(context, event_queue, result.message or f"Nothing generated for {ctx}.")
    await reply(context, event_queue, summarize_implement(result))
