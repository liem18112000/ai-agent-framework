"""InterrogationAgent — the shared HITL round loop for KGA refine + TPD define (Option B).

The A0 spike proved the mechanic; this wires it to the REAL engines. Per invocation it advances a
reused session (RefineSession for KGA, PlanSession for TPD) by one round and pauses (ends the
invocation); the next A2A turn resumes. State persistence reuses each session's OWN bank rehydration
(already tested, carries insights/decisions/questions + B0–B6), keyed by the context id (= the ADK
session id, which the bridge holds constant across the pipeline).

One class, two configs — the only differences (session class, state store, finalize summary) live in
a `SessionSpec`. The "refine" spec (RefineSession — a `common` type) is registered here; the "plan"
spec is registered from the test_plan_definition package, so `common` never imports an agent (I6).

LLM-touching steps (`next_questions`, `finalize`) run via `asyncio.to_thread` (invariant I3). Both
sessions select Claude-on-Vertex when configured and the heuristic otherwise (I5/I7).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from google.adk.agents import BaseAgent

from common.adk.events import incoming_text, now, text_event
from common.interrogate.present import render_questions
from common.memory.factory import build_bank
from common.monitoring import get_logger

log = get_logger("adk.interrogation")


@dataclass(frozen=True)
class SessionSpec:
    """The four things that differ between refine (KGA) and define (TPD)."""

    make: Callable            # (bank, ctx_id, rounds, now) -> a fresh session
    rehydrate: Callable       # (bank, ctx_id) -> a resumed session
    read_state: Callable      # (bank, ctx_id) -> dict ({} if none)
    mark_done: Callable       # (bank, ctx_id) -> None
    summarize: Callable       # (result) -> str


_SPECS: dict[str, SessionSpec] = {}


def register_spec(kind: str, spec: SessionSpec) -> None:
    _SPECS[kind] = spec


class InterrogationAgent(BaseAgent):
    """Config: the round set, the agent prefix (KGA/TPD), the human-facing header, and the kind
    ('refine' | 'plan') selecting the registered SessionSpec."""

    rounds: tuple[str, ...]
    agent_prefix: str = "KGA"
    header: str = "Please answer the open questions (Q-id: your choice)."
    kind: str = "refine"

    async def _run_async_impl(self, ctx):
        spec = _SPECS[self.kind]
        bank = await asyncio.to_thread(build_bank)
        ctx_id = self._context_id(ctx)
        state = spec.read_state(bank, ctx_id) or {}
        live = bool(state) and not state.get("done")
        incoming = incoming_text(ctx)

        if not live:
            session = spec.make(bank, ctx_id, self.rounds, now())
            if session.is_empty():
                yield text_event(self.name, f"Nothing to {self.kind} — run the prior step first.")
                return
        else:
            session = spec.rehydrate(bank, ctx_id)
            if incoming:  # continuation turn: the message is the answer to the paused round
                await session.submit(incoming)

        rnd = await asyncio.to_thread(session.next_questions)
        if rnd is None:
            result = await asyncio.to_thread(session.finalize)
            spec.mark_done(bank, ctx_id)
            yield text_event(self.name, spec.summarize(result), state_delta={"io_done": True})
            return

        session.save()
        yield text_event(
            self.name, render_questions(ctx_id, rnd, header=self.header),
            state_delta={"io_active": True, "io_pack_ctx": ctx_id},
        )

    def _context_id(self, ctx) -> str:
        # The pack/plan was produced under this id; the bridge reuses one id across the pipeline,
        # so the ADK session id IS the context id (state override kept for flexibility).
        return (ctx.session.state or {}).get("io_pack_ctx") or ctx.session.id


# --- the "refine" spec (KGA) — RefineSession is a `common` type, so it belongs here --- #
def _refine_summary(result) -> str:
    gaps = getattr(result, "open_gaps", None) or getattr(result, "gaps", []) or []
    conf = getattr(result, "confidence", "")
    n = len(getattr(result, "insights", []) or [])
    return f"Refinement complete (confidence: {conf}). {n} insights, {len(gaps)} open gaps."


def _register_refine_spec() -> None:
    from common.interrogate.loop import RefineSession

    register_spec("refine", SessionSpec(
        make=lambda bank, cid, rounds, now: RefineSession(bank, cid, rounds=rounds, run_id=cid, now=now),
        rehydrate=lambda bank, cid: RefineSession.rehydrate(bank, cid),
        read_state=lambda bank, cid: bank.read_refine_state(cid),
        mark_done=lambda bank, cid: bank.write_refine_state(cid, {"done": True}),
        summarize=_refine_summary,
    ))


_register_refine_spec()
