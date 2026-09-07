"""Knowledge Refinement (Step 2) handler — multi-turn interrogation over A2A.

`refine <ctx>` starts an interrogation; the agent pauses in `input-required` with a question set;
the client answers on the same task and the agent resumes, persisting insights until it can
restate a confirmed understanding. Read helpers: `get-questions <ctx>`, `get-understanding <ctx>`.
"""

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
from common.interrogate import RefineSession, present
from common.interrogate.loop import RefineResult
from common.memory import retrieve
from knowledge_gathering.executor.common import build_client, now, reply
from knowledge_gathering.loop import crawl
from knowledge_gathering.monitoring import get_logger

log = get_logger("executor.refine")


async def _recall_into(session, bank) -> None:
    """L4: inject prior lessons into the pack so refine doesn't re-learn them — structural ∪
    semantic under a DB backend (M4b), structural-only on GCS. Best-effort, flag-gated."""
    if not learn.recall_enabled("KGA"):
        return
    try:
        grounded = session.pack.grounded
        session.pack.lessons = await retrieve.recall_lessons(
            bank, seed_refs={n.id for n in grounded},
            query_text=" ".join(n.title for n in grounded if n.title),
        )
    except Exception as exc:  # noqa: BLE001 — recall is best-effort
        log.warning("A2A refine: lesson recall skipped (%s)", exc)


def _capture_refine(bank, pack_ctx: str, result: RefineResult) -> None:
    """L2: enqueue an async capture of this session's human decisions (off the request path)."""
    if not learn.capture_enabled("KGA"):
        return
    try:
        sigs = learn.from_decisions(result.insights)
        if sigs:
            learn.enqueue(bank, learn.CaptureJob(
                id=f"cap-refine-{pack_ctx}", context_id=pack_ctx,
                run_id=result.run.run_id if result.run else "", step="refine",
                signals=[asdict(s) for s in sigs]))
    except Exception as exc:  # noqa: BLE001 — capture must not break refine
        log.warning("A2A refine: lesson capture skipped (%s)", exc)


def wants_refine(text: str) -> bool:
    t = text.strip().lower()
    if t.startswith("refine"):
        return True
    if t.startswith("{"):
        try:
            d = json.loads(text)
        except json.JSONDecodeError:
            return False
        return "context_id" in d or "answers" in d
    return False


def live_session(bank, a2a_ctx: str) -> bool:
    if not a2a_ctx:
        return False
    pack_ctx = bank.resolve_session(a2a_ctx)
    return bool(pack_ctx and not bank.read_refine_state(pack_ctx).get("done"))


def extract_ctx(text: str) -> str | None:
    return present.extract_ctx(text, ("refine", "get-questions", "get-understanding"))


def render_questions(context_id: str, open_qs) -> str:
    return present.render_questions(context_id, open_qs, header="Refinement questions")


def summarize_refine(result: RefineResult) -> str:
    lines = [
        (
            f"Refinement complete (confidence: {result.confidence}). "
            f"{len(result.insights)} insights, {len(result.open_gaps)} open gaps, "
            f"{len(result.new_seeds)} re-seeds."
        ),
        "",
        result.understanding.strip(),
    ]
    if result.open_gaps:
        lines += ["", "Declared gaps: " + "; ".join(result.open_gaps)]
    return "\n".join(lines)


def build_gatherer(ex, bank, pack_ctx: str):
    """A re-seed gatherer running the read-only gather crawl, or None if no client."""
    if ex._gatherer is not None:
        return ex._gatherer
    try:
        client = ex._client or build_client()
    except Exception:  # noqa: BLE001 — no creds → re-seeds recorded but not re-gathered
        return None

    async def gatherer(seed: str) -> None:
        await crawl(client, bank, seed, distiller=ex._distiller, run_id=pack_ctx)

    return gatherer


async def run_read_helper(ex, context: RequestContext, event_queue: EventQueue, bank, text: str) -> None:
    ctx = extract_ctx(text)
    if not ctx:
        return await reply(context, event_queue, "Provide a context id.")
    if text.lower().startswith("get-understanding"):
        return await reply(context, event_queue,
                           bank.read_understanding(ctx) or f"No understanding yet for {ctx}.")
    qs = bank.read_questions(ctx)
    body = json.dumps([{"id": q.id, "round": q.round, "question": q.question, "status": q.status}
                       for q in qs], indent=1)
    await reply(context, event_queue, body if qs else f"No questions yet for {ctx}.")


async def run_refine(ex, context: RequestContext, event_queue: EventQueue,
                     bank, text: str, a2a_ctx: str) -> None:
    pack_ctx = bank.resolve_session(a2a_ctx) or extract_ctx(text)
    if not pack_ctx:
        return await reply(context, event_queue, "Provide a context id, e.g. 'refine run-6f2a'.")

    state = bank.read_refine_state(pack_ctx)
    continuation = bool(state) and not state.get("done")
    updater = TaskUpdater(event_queue, context.task_id, context.context_id)

    if not continuation:  # turn 1 — start the interrogation
        session = RefineSession(
            bank, pack_ctx, seed=pack_ctx, generator=ex._generator,
            understander=ex._understander, gatherer=build_gatherer(ex, bank, pack_ctx),
            run_id=f"refine-{(a2a_ctx or pack_ctx)[:8]}", now=now(),
        )
        if session.is_empty():
            return await reply(context, event_queue,
                               f"Nothing to refine for {pack_ctx}; run gather first.")
        bank.link_session(a2a_ctx, pack_ctx)
    else:  # continuation — ingest answers, advance
        session = RefineSession.rehydrate(
            bank, pack_ctx, generator=ex._generator, understander=ex._understander,
            gatherer=build_gatherer(ex, bank, pack_ctx),
        )
        log.info("A2A refine: ingesting answers for %s", pack_ctx)
        await session.submit(text)

    await _recall_into(session, bank)  # L4: prior lessons → pack preamble (flag-gated)

    if context.current_task is None:  # enqueue the initial Task before any status-update event
        await event_queue.enqueue_event(new_task_from_user_message(context.message))

    # next_questions()/finalize() run the (possibly Claude-on-Vertex) generators synchronously;
    # offload so a long LLM call never stalls the event loop and starves Cloud Run's /livez probe.
    open_qs = await asyncio.to_thread(session.next_questions)
    if open_qs is None:  # done — finalize + complete
        result = await asyncio.to_thread(session.finalize)
        bank.write_refine_state(pack_ctx, {"done": True})
        _capture_refine(bank, pack_ctx, result)  # L2: enqueue async lesson capture (flag-gated)
        log.info("A2A refine done: %d insights", len(result.insights))
        return await updater.complete(
            updater.new_agent_message([a2a_pb2.Part(text=summarize_refine(result))]))
    session.save()  # pause for the human
    await updater.requires_input(
        updater.new_agent_message([a2a_pb2.Part(text=render_questions(pack_ctx, open_qs))]))
