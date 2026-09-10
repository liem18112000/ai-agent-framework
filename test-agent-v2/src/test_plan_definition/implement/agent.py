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


def _quality_line(result: ImplementResult) -> str:
    """One-line P4 assured-loop verdict for the human, when the loop ran (§3.4)."""
    q = result.quality
    if q is None:
        return ""
    verdict = "PASS" if q.accepted else "BELOW BAR"
    return (f"  Quality (assured loop, {q.rounds} round(s)): {verdict} — score "
            f"{q.final_score:.2f} vs threshold {q.threshold:.2f}. {q.note}\n")


def summarize_implement(result: ImplementResult) -> str:
    happy = sum(s.kind == HAPPY for s in result.scenarios)
    negative = sum(s.kind == NEGATIVE for s in result.scenarios)
    titles = "\n".join(f"- [{s.kind}] {s.title}" for s in result.scenarios)
    feature = "  Exported a BDD .feature.\n" if result.feature else ""
    coverage = f"  {result.coverage_summary}\n" if result.coverage_summary else ""
    return (f"Implement complete: {len(result.test_data)} test-data, {len(result.scenarios)} "
            f"scenarios ({happy} happy / {negative} negative), {len(result.steps)} steps.\n"
            f"{feature}{coverage}{_quality_line(result)}\n{titles}")


class ImplementAgent(BaseAgent):
    """One-shot artifact generation (the `generate` leaf; also the autonomous pipeline's implement)."""

    async def _run_async_impl(self, ctx):
        ctx_id = ctx.session.id
        words = incoming_text(ctx).lower().split()
        bank = build_bank()
        result = await implement_plan(bank, ctx_id, run_id=f"impl-{ctx_id[:8]}", now=_now(),
                                      detail="detail" in words, assured="assured" in words)
        _capture_implement(bank, ctx_id, result)
        if not result.scenarios:
            yield text_event(self.name, result.message or f"Nothing generated for {ctx_id}.")
            return
        yield text_event(self.name, summarize_implement(result))


class ImplementOrchestrator(BaseAgent):
    """Q3/Q4: the interactive implement stage as an ORCHESTRATOR nesting two sub-agents — `interrogate`
    (case-design/data-design/step-oracle rounds) then `generate` (artifact generation). It runs the
    interrogation until the design is confirmed, then chains straight into generation on that turn."""

    interrogate: BaseAgent
    generate: BaseAgent

    async def _run_async_impl(self, ctx):
        from common.testplan import memory as store

        bank = build_bank()
        ctx_id = (ctx.session.state or {}).get("io_pack_ctx") or ctx.session.id
        if not (store.read_implement_state(bank, ctx_id) or {}).get("done"):
            async for ev in self.interrogate.run_async(ctx):  # start or continue the interrogation
                yield ev
            if not (store.read_implement_state(bank, ctx_id) or {}).get("done"):
                return  # still interrogating — waiting for the next answer turn
        async for ev in self.generate.run_async(ctx):  # design confirmed → generate artifacts
            yield ev


def build_implement_agent(name: str = "implement") -> ImplementOrchestrator:
    from test_plan_definition.implement.interrogate import build_interrogate_agent

    interrogate, generate = build_interrogate_agent(), ImplementAgent(name="generate")
    return ImplementOrchestrator(name=name, interrogate=interrogate, generate=generate,
                                 sub_agents=[interrogate, generate])
