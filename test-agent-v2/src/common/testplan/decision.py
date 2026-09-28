"""Distill answers (and self-answers) into provenance-carrying PlanDecision records."""

from __future__ import annotations

# TPL-04: reuse the interrogate/insight helpers (source-ref selection, statement, rejected) rather
# than re-implementing them here (they had already drifted — the arrow glyph). `_source_refs` takes a
# Pack, so pass `plan_pack.pack`; only the PlanDecision construction is TPD-specific.
from common.interrogate.insight import _rejected, _source_refs, _statement
from common.models import Answer, Question
from common.testplan.models import ASSUMPTION, DECISION, PlanDecision
from common.testplan.pack import PlanPack


def decision_from_answer(
    answer: Answer, question: Question, plan_pack: PlanPack, *, run_id: str = "", now: str = ""
) -> PlanDecision:
    chosen = answer.chosen_option or answer.text
    return PlanDecision(
        id=f"plan-decision:{plan_pack.context_id}:{question.id}", kind=DECISION,
        context_id=plan_pack.context_id, question_id=question.id,
        statement=_statement(question, chosen), round=question.round, chosen=chosen,
        answered_by=answer.answered_by,
        confidence="high" if answer.answered_by == "human" else "medium",
        source_refs=_source_refs(question, plan_pack.pack), created_at=now, run_id=run_id,
        rationale=answer.text, rejected=_rejected(question, answer.chosen_option),
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
        source_refs=_source_refs(question, plan_pack.pack), created_at=now, run_id=run_id,
        rationale="Derived from the refined pack; a vetoable assumption, not a settled decision.",
    )
