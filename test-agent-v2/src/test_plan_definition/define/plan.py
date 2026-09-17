"""Assemble the confirmed TestPlan from plan decisions, and restate a human-facing brief."""

from __future__ import annotations

from collections.abc import Callable

from common.adk.model import complete, model_configured
from common.models import Question
from common.testplan.llm.prompts import brief_prompt, pack_block
from common.testplan.models import ASSUMPTION, DRAFT, PlanDecision, TestPlan
from common.testplan.pack import PlanPack

_METHODOLOGIES = ("api", "e2e", "ui")

Restater = Callable[[TestPlan, PlanPack, list[Question]], str]


def confidence(decisions: list[PlanDecision], open_questions: list[Question]) -> str:
    if open_questions:
        return "low"
    return "medium" if any(d.kind == ASSUMPTION or d.confidence == "low" for d in decisions) else "high"


def assemble_plan(
    plan_pack: PlanPack, decisions: list[PlanDecision], *, conf: str, status: str = DRAFT,
    run_id: str = "", now: str = "",
) -> TestPlan:
    methodology: list[str] = []
    scope: list[str] = []
    out_of_scope: list[str] = []
    metrics: list[str] = []
    test_design: list[str] = []
    for d in decisions:
        ref = d.source_refs[0] if d.source_refs else ""
        if d.round == "methodology":
            methodology += [m for m in _METHODOLOGIES if m in d.chosen.lower()]
        elif d.round == "scope":
            (out_of_scope if d.chosen.lower().startswith("out of") else scope).append(ref or d.chosen)
        elif d.round == "metrics":
            metrics.append(d.chosen)
        elif d.round == "test-design":
            test_design.append(d.chosen)

    grounded = plan_pack.pack.grounded
    if not scope and grounded:
        scope = [grounded[0].id]
    source_refs = sorted({r for d in decisions for r in d.source_refs}
                         | {n.id for n in plan_pack.pack.insights})
    ctx = plan_pack.context_id
    return TestPlan(
        id=f"plan:{ctx}", context_id=ctx, methodology=methodology or ["api"], scope=scope,
        out_of_scope=out_of_scope, metrics=metrics, test_design=test_design, confidence=conf,
        source_refs=source_refs, status=status, created_at=now, run_id=run_id,
    )


def make_restater() -> Restater:
    """Provider-sourced prose brief when the model is configured, else the heuristic assembly."""
    if not model_configured():
        return heuristic_brief

    def restater(plan: TestPlan, plan_pack: PlanPack, opens: list[Question]) -> str:
        summary = plan_pack.summary_text()
        prompt = brief_prompt(plan, summary, [q.question for q in opens], include_context=False)
        return complete(prompt, max_tokens=700, cache_prefix=pack_block(summary),
                        tier="fast").strip() + "\n"  # brief restatement → fast tier

    return restater


def restate(plan: TestPlan, plan_pack: PlanPack, open_questions: list[Question],
           *, restater: Restater | None = None) -> str:
    return (restater or make_restater())(plan, plan_pack, open_questions)


def heuristic_brief(plan: TestPlan, plan_pack: PlanPack, open_questions: list[Question]) -> str:
    grounded = plan_pack.pack.grounded
    subject = grounded[0].title if grounded else plan.context_id

    def bullets(items: list[str]) -> str:
        return "\n".join(f"- {i}" for i in items) or "- (none yet)"

    lines = [
        f"## Test Plan brief — {subject} (confidence: {plan.confidence})",
        "",
        f"**Methodology:** {', '.join(plan.methodology)}",
        "",
        f"**Test-design method(s):** {', '.join(plan.test_design) or '(default per behaviour)'}",
        "",
        "**In scope:**",
        bullets(plan.scope),
        "",
    ]
    if plan.out_of_scope:
        lines += ["**Out of scope:**", bullets(plan.out_of_scope), ""]
    lines += ["**Passed means:**", bullets(plan.metrics), "", "**Open questions:**",
             bullets([q.question for q in open_questions]) if open_questions
             else "- none above the confidence bar"]
    return "\n".join(lines) + "\n"
