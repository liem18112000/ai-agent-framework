"""Test Plan definition (Stage A) handler — multi-turn interrogation over A2A."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict

from a2a.helpers.proto_helpers import new_task_from_user_message
from a2a.server.agent_execution import RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import a2a_pb2

from common import learn
from common.interrogate import present
from common.memory import retrieve
from test_plan_definition import memory as store
from test_plan_definition.define.loop import PlanResult, PlanSession
from test_plan_definition.executor.common import now, reply
from test_plan_definition.models import CONFIRMED
from test_plan_definition.monitoring import get_logger

log = get_logger("executor.define")


async def _recall_into(session, bank) -> None:
    """L4: inject prior lessons into the plan pack — structural ∪ semantic under a DB backend"""
    if not learn.recall_enabled("TPD"):
        return
    try:
        pack = session.plan_pack.pack
        pack.lessons = await retrieve.recall_lessons(
            bank, seed_refs={n.id for n in pack.grounded},
            query_text=" ".join(n.title for n in pack.grounded if n.title),
        )
    except Exception as exc:  # noqa: BLE001 — recall is best-effort
        log.warning("A2A define: lesson recall skipped (%s)", exc)


def _capture_define(bank, pack_ctx: str, result: PlanResult) -> None:
    """L3: enqueue an async capture of this session's human decisions (off the request path)."""
    if not learn.capture_enabled("TPD"):
        return
    try:
        sigs = learn.from_decisions(result.decisions)
        if sigs:
            learn.enqueue(bank, learn.CaptureJob(
                id=f"cap-define-{pack_ctx}", context_id=pack_ctx, step="define",
                signals=[asdict(s) for s in sigs]))
    except Exception as exc:  # noqa: BLE001 — capture must not break define
        log.warning("A2A define: lesson capture skipped (%s)", exc)


def wants_define(text: str) -> bool:
    t = text.strip().lower()
    if t.startswith("define"):
        return True
    if t.startswith("{"):
        try:
            return "context_id" in json.loads(text)
        except json.JSONDecodeError:
            return False
    return False


def live_session(bank, a2a_ctx: str) -> bool:
    """True when this conversation has an ongoing (not-done) define session."""
    if not a2a_ctx:
        return False
    pack_ctx = store.resolve_session(bank, a2a_ctx) or a2a_ctx
    st = store.read_plan_state(bank, pack_ctx)
    return bool(st) and not st.get("done")


def extract_ctx(text: str) -> str | None:
    return present.extract_ctx(text, ("define", "get-test-plan", "get-scenarios"))


def render_questions(context_id: str, open_qs) -> str:
    return present.render_questions(context_id, open_qs, header="Test Plan questions")


def summarize_define(result: PlanResult) -> str:
    status = result.plan.status if result.plan else "n/a"
    lines = [
        (
            f"Plan definition complete (status: {status}, confidence: {result.confidence}). "
            f"{len(result.decisions)} decisions, {len(result.open_gaps)} open gaps."
        ),
        "",
        result.brief.strip(),
    ]
    if result.open_gaps:
        lines += ["", "Declared gaps: " + "; ".join(result.open_gaps)]
    return "\n".join(lines)


async def run_read_helper(ex, context: RequestContext, event_queue: EventQueue, bank, text: str) -> None:
    ctx = extract_ctx(text)
    if not ctx:
        return await reply(context, event_queue, "Provide a context id.")
    if text.lower().startswith("get-test-plan"):
        return await reply(context, event_queue,
                           store.read_plan_brief(bank, ctx) or f"No test plan yet for {ctx}.")
    return await reply(context, event_queue,
                       store.read_scenarios_md(bank, ctx)
                       or f"No scenarios yet for {ctx} — run implement first.")


async def run_approve(ex, context: RequestContext, event_queue: EventQueue, bank, text: str,
                      a2a_ctx: str = "") -> None:
    """The reconfirm gate — lock the plan to 'confirmed' so implement may run."""
    ctx = extract_ctx(text) or a2a_ctx
    if not ctx:
        return await reply(context, event_queue, "Provide a context id, e.g. 'approve run-6f2a'.")
    plan = store.read_plan(bank, ctx)
    if plan is None:
        return await reply(context, event_queue,
                           f"No test plan to approve for {ctx}; run define first.")
    if plan.status != CONFIRMED:
        plan.status = CONFIRMED
        store.write_plan(bank, plan)
    store.write_plan_state(bank, ctx, {"done": True})
    brief = store.read_plan_brief(bank, ctx) or ""
    await reply(context, event_queue, f"APPROVED {ctx} (status: confirmed)\n\n{brief}")


async def run_define(ex, context: RequestContext, event_queue: EventQueue,
                     bank, text: str, a2a_ctx: str) -> None:
    pack_ctx = store.resolve_session(bank, a2a_ctx) or extract_ctx(text) or a2a_ctx
    if not pack_ctx:
        return await reply(context, event_queue, "Provide a context id, e.g. 'define run-6f2a'.")

    state = store.read_plan_state(bank, pack_ctx)
    continuation = bool(state) and not state.get("done")
    updater = TaskUpdater(event_queue, context.task_id, context.context_id)

    if not continuation:
        session = PlanSession(
            bank, pack_ctx, seed=pack_ctx, generator=ex._generator, restater=ex._restater,
            run_id=f"plan-{(a2a_ctx or pack_ctx)[:8]}", now=now(),
        )
        if session.is_empty():
            return await reply(context, event_queue,
                               f"Nothing to plan for {pack_ctx}; run gather + refine (approve) first.")
        store.link_session(bank, a2a_ctx, pack_ctx)
    else:
        session = PlanSession.rehydrate(
            bank, pack_ctx, generator=ex._generator, restater=ex._restater)
        log.info("A2A define: ingesting answers for %s", pack_ctx)
        await session.submit(text)

    await _recall_into(session, bank)

    if context.current_task is None:
        await event_queue.enqueue_event(new_task_from_user_message(context.message))

    open_qs = await asyncio.to_thread(session.next_questions)
    if open_qs is None:
        result = await asyncio.to_thread(session.finalize)
        _capture_define(bank, pack_ctx, result)
        log.info("A2A define done: %d decisions", len(result.decisions))
        return await updater.complete(
            updater.new_agent_message([a2a_pb2.Part(text=summarize_define(result))]))
    session.save()
    await updater.requires_input(
        updater.new_agent_message([a2a_pb2.Part(text=render_questions(pack_ctx, open_qs))]))
