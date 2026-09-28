"""ImplementAgent — the `generate` sub-agent: one-shot artifact generation (custom ADK BaseAgent),
plus the lesson capture and reply summary. Also the autonomous SequentialAgent's implement step."""

from __future__ import annotations

import contextlib
import os
import re
from dataclasses import asdict

from google.adk.agents import BaseAgent

from common import learn
from common.adk.events import incoming_text, now, text_event
from common.memory.factory import build_bank
from common.testplan.models import HAPPY, NEGATIVE
from test_plan_definition.implement.generate.pipeline import ImplementResult, implement_plan
from test_plan_definition.monitoring import get_logger

log = get_logger("tpd.implement")


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


_DEFAULT_STEP_ROUNDS = 1


def _step_rounds() -> int:
    """Assured rounds per ``implement_plan`` call (env ``TPD_IMPLEMENT_STEP_ROUNDS``, default 1). One
    round ≈ one generate + one (cheap) judge, well under the client's ~300s MCP tool idle timeout — the
    client re-invokes until '[state: done]'. Set high (≈ MAX_ITERS) to restore one-shot blocking."""
    with contextlib.suppress(KeyError, ValueError, TypeError):
        return max(1, int(os.environ["TPD_IMPLEMENT_STEP_ROUNDS"]))
    return _DEFAULT_STEP_ROUNDS


def summarize_progress(result: ImplementResult) -> str:
    """The in-progress reply when the assured loop paused with rounds remaining (``done=False``)."""
    q = result.quality
    rounds, score = (q.rounds, f"{q.final_score:.2f}") if q else (0, "n/a")
    bar = f"{q.threshold:.2f}" if q else "n/a"
    return (f"Assured loop in progress: {len(result.scenarios)} scenario(s) so far, {rounds} round(s) "
            f"done (best score {score} vs bar {bar}). Re-run implement_plan(context_id) to continue, "
            'or implement_plan(guidance="…") to steer the next round.')


def summarize_implement(result: ImplementResult) -> str:
    happy = sum(s.kind == HAPPY for s in result.scenarios)
    negative = sum(s.kind == NEGATIVE for s in result.scenarios)
    titles = "\n".join(f"- [{s.kind}] {s.title}" for s in result.scenarios)
    feature = "  Exported a BDD .feature.\n" if result.feature else ""
    coverage = f"  {result.coverage_summary}\n" if result.coverage_summary else ""
    quality = ""  # the P4 assured-loop verdict + per-round AI critique — the reference view (§3.4)
    if (q := result.quality) is not None:
        verdict = "PASS" if q.accepted else "BELOW BAR"
        quality = (f"  Quality (assured loop, {q.rounds} round(s)): {verdict} — score "
                   f"{q.final_score:.2f} vs threshold {q.threshold:.2f}. {q.note}\n")
        for it in q.iterations:  # per-round evaluation + criticism, so the client can view the AI's reasoning
            critique = "; ".join(it.get("issues", [])) or "—"
            quality += (f"    round {it.get('iter')}: score {it.get('score')} "
                        f"({'accepted' if it.get('accepted') else 'below bar'}) · critique: {critique}\n")
        if q.reflections:
            quality += "    suggested fixes: " + "; ".join(q.reflections) + "\n"
        if not q.accepted:
            quality += ('    ⟳ not accepted — re-run implement_plan(guidance="<your steer>") for '
                        "another round, or accept these as-is.\n")
    return (f"Implement complete: {len(result.test_data)} test-data, {len(result.scenarios)} "
            f"scenarios ({happy} happy / {negative} negative), {len(result.steps)} steps.\n"
            f"{feature}{coverage}{quality}\n{titles}")


class ImplementAgent(BaseAgent):
    """One-shot artifact generation (the `generate` leaf; also the autonomous pipeline's implement)."""

    async def _run_async_impl(self, ctx):
        ctx_id = ctx.session.id
        head, _, tail = incoming_text(ctx).partition("guidance:")  # optional steer for the next round
        # R6 per-piece rigor. It MUST be sent before the guidance line: `guidance:`
        # partitions the message and swallows everything after it into `tail`.
        rigor = int(m.group(1)) if (m := re.search(r"rigor:\s*(\d+)", head)) else None
        bank = build_bank()
        result = await implement_plan(bank, ctx_id, run_id=f"impl-{ctx_id[:8]}", now=now(),
                                      detail="detail" in head.lower().split(), guidance=tail.strip(),
                                      max_rounds=_step_rounds(), rigor=rigor)
        if not result.scenarios:
            yield text_event(self.name, result.message or f"Nothing generated for {ctx_id}.")
            return
        if not result.done:  # assured loop paused — client re-invokes to continue (multi-turn, like define)
            yield text_event(self.name, "[state: in_progress]\n" + summarize_progress(result))
            return
        _capture_implement(bank, ctx_id, result)  # harvest lessons once, on the finished pass
        yield text_event(self.name, "[state: done]\n" + summarize_implement(result))
