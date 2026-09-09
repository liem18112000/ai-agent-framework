"""Distill answers (and self-answers) into provenance-carrying PlanDecision records."""

from __future__ import annotations

from common.models import Answer, Question
from common.testplan.models import ASSUMPTION, DECISION, PlanDecision
from common.testplan.pack import PlanPack


def _source_refs(question: Question, plan_pack: PlanPack) -> list[str]:
    if question.applies_to:
        return [question.applies_to]
    primary = plan_pack.pack.grounded[0].id if plan_pack.pack.grounded else plan_pack.pack.seed
    return [primary] if primary else []


def _statement(question: Question, chosen: str) -> str:
    return f"{question.question.rstrip('?')} -> {chosen}"


def decision_from_answer(
    answer: Answer, question: Question, plan_pack: PlanPack, *, run_id: str = "", now: str = ""
) -> PlanDecision:
    chosen = answer.chosen_option or answer.text
    rejected = [o["label"] for o in question.options
               if o.get("label") and o["label"] != answer.chosen_option]
    return PlanDecision(
        id=f"plan-decision:{plan_pack.context_id}:{question.id}", kind=DECISION,
        context_id=plan_pack.context_id, question_id=question.id,
        statement=_statement(question, chosen), round=question.round, chosen=chosen,
        answered_by=answer.answered_by,
        confidence="high" if answer.answered_by == "human" else "medium",
        source_refs=_source_refs(question, plan_pack), created_at=now, run_id=run_id,
        rationale=answer.text, rejected=rejected,
    )


def assumption_from_self_answer(
    question: Question, plan_pack: PlanPack, *, run_id: str = "", now: str = ""
) -> PlanDecision:
    chosen = question.recommendation or "(agent default)"
    return PlanDecision(
        id=f"plan-decision:{plan_pack.context_id}:{question.id}", kind=ASSUMPTION,
        context_id=plan_pack.context_id, question_id=question.id,
        statement=_statement(question, chosen), round=question.round, chosen=chosen,
        answered_by="agent-self", confidence="low",
        source_refs=_source_refs(question, plan_pack), created_at=now, run_id=run_id,
        rationale="Derived from the refined pack; a vetoable assumption, not a settled decision.",
    )
