"""InterrogationAgent — the shared HITL round loop for KGA refine + TPD define (Option B)."""

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
    """The things that differ between refine (KGA) and define (TPD)."""

    make: Callable
    rehydrate: Callable
    read_state: Callable
    mark_done: Callable
    summarize: Callable
    pack_of: Callable = lambda s: s.pack  # locate the Pack on the session (for L4 lesson recall)


_SPECS: dict[str, SessionSpec] = {}


def register_spec(kind: str, spec: SessionSpec) -> None:
    _SPECS[kind] = spec


class InterrogationAgent(BaseAgent):
    """Config: the round set, the agent prefix (KGA/TPD), the human-facing header, and the kind"""

    rounds: tuple[str, ...]
    agent_prefix: str = "KGA"
    header: str = "Please answer the open questions (Q-id: your choice)."
    kind: str = "refine"

    async def _run_async_impl(self, ctx):
        spec = _SPECS[self.kind]
        bank = await asyncio.to_thread(build_bank)
        ctx_id = self._context_id(ctx)
        live = bool(state := spec.read_state(bank, ctx_id) or {}) and not state.get("done")

        if not live:
            session = spec.make(bank, ctx_id, self.rounds, now())
            if session.is_empty():
                yield text_event(self.name, f"Nothing to {self.kind} — run the prior step first.")
                return
        else:
            session = spec.rehydrate(bank, ctx_id)
            if incoming := incoming_text(ctx):
                await session.submit(incoming)

        await _recall_into(bank, spec.pack_of(session), self.agent_prefix)  # L4: prior lessons → pack

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
        return (ctx.session.state or {}).get("io_pack_ctx") or ctx.session.id


async def _recall_into(bank, pack, prefix: str) -> None:
    """L4: inject prior lessons into the pack so the interrogation doesn't re-learn them — structural
    ∪ semantic under a DB backend (M4b, two-tier), structural-only on GCS. Flag-gated (RECALL_LESSONS,
    default off) + best-effort, so the default path is unchanged. Runs every turn (mirrors v1's
    executor `_recall_into`); `pack.lessons` renders into the question prompt via `summary_text`."""
    from common import learn

    if pack is None or not learn.recall_enabled(prefix):
        return
    try:
        from common.memory import retrieve

        grounded = pack.grounded
        pack.lessons = await retrieve.recall_lessons(
            bank, seed_refs={n.id for n in grounded},
            query_text=" ".join(n.title for n in grounded if n.title),
        )
    except Exception as exc:  # noqa: BLE001 — recall is best-effort; never block the interrogation
        log.warning("interrogation: lesson recall skipped (%s)", exc)


def _refine_summary(result) -> str:
    return (f"Refinement complete (confidence: {getattr(result, 'confidence', '')}). "
            f"{len(getattr(result, 'insights', []) or [])} insights, "
            f"{len(getattr(result, 'open_gaps', None) or getattr(result, 'gaps', []) or [])} open gaps.")


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
