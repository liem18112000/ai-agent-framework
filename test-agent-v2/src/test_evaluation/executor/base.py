"""The A2A executor — one-shot pack evaluation."""

from __future__ import annotations

import asyncio

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue

from common.executor import build_bank, reply
from common.interrogate import present
from test_evaluation.engine import evaluate_pack
from test_evaluation.golden import load_golden, load_golden_plans
from test_evaluation.models import EvalCase, EvalReport, PlanEvalCase, PlanReport
from test_evaluation.monitoring import get_logger
from test_evaluation.plan_engine import evaluate_plan

log = get_logger("executor")


def extract_ctx(text: str) -> str | None:
    return present.extract_ctx(text, ("evaluate", "score", "plan", "pack"))


def _is_plan(text: str) -> bool:
    return "plan" in text.lower().split()


def golden_for(ctx: str) -> EvalCase | None:
    """The golden pack case whose seed or fixture matches this context (best-effort)."""
    for d in load_golden():
        if ctx in (d.get("seed"), d.get("fixture")):
            return EvalCase.from_dict(d)
    return None


def golden_plan_for(ctx: str) -> PlanEvalCase | None:
    """The golden plan case whose seed or fixture matches this context (best-effort)."""
    for d in load_golden_plans():
        if ctx in (d.get("seed"), d.get("fixture")):
            return PlanEvalCase.from_dict(d)
    return None


def render(r: EvalReport) -> str:
    lines = [
        f"Pack Quality Score for {r.context_id}: {r.pqs}",
        "Components: " + ", ".join(f"{k}={v:.2f}" for k, v in r.components.as_dict().items()),
    ]
    if r.retrieval:
        lines.append(f"Retrieval: recall={r.retrieval.recall:.2f} "
                     f"precision={r.retrieval.precision:.2f} leaked={r.retrieval.leaked}")
    if r.entities and r.entities.missing:
        lines.append("Missing entities: " + ", ".join(r.entities.missing))
    return "\n".join(lines)


def render_plan(r: PlanReport) -> str:
    lines = [
        f"Test-Plan Score for {r.context_id}: {r.tps}",
        "Components: " + ", ".join(f"{k}={v:.2f}" for k, v in r.components.as_dict().items()),
    ]
    if r.scope:
        lines.append(f"Scope: precision={r.scope.precision:.2f} recall={r.scope.recall:.2f} "
                     f"leaked={r.scope.leaked}")
    if r.coverage:
        lines.append(f"Coverage: ac_recall={r.coverage.ac_recall:.2f} "
                     f"matrix={r.coverage.matrix_completeness:.2f} uncovered={r.coverage.uncovered}")
    if r.oracle:
        lines.append(f"Oracle strength: {r.oracle.score:.2f} {r.oracle.distribution}")
    if r.placeholders and not r.placeholders.passed:
        lines.append(f"Placeholder leak: {r.placeholders.leaked_tokens} (path {r.placeholders.provenance})")
    return "\n".join(lines)


class TestEvaluationExecutor(AgentExecutor):
    def __init__(self, *, bank=None) -> None:
        self._bank = bank

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        text = (context.get_user_input() or "").strip()
        a2a_ctx = context.context_id or ""
        try:
            bank = self._bank or build_bank()
        except Exception:  # noqa: BLE001 — bank is the one hard dependency
            return await reply(context, event_queue, "Config error: memory bank unavailable.")

        ctx = extract_ctx(text) or a2a_ctx
        if not ctx:
            return await reply(context, event_queue, "Provide a context id, e.g. 'evaluate run-6f2a'.")
        if _is_plan(text):
            report = await asyncio.to_thread(evaluate_plan, bank, ctx, golden_plan_for(ctx))
            return await reply(context, event_queue, render_plan(report))
        report = await asyncio.to_thread(evaluate_pack, bank, ctx, golden_for(ctx))
        await reply(context, event_queue, render(report))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("cancel is not supported yet")
