"""Distill answers (and self-answers) into provenance-carrying Insight records."""

from __future__ import annotations

from common.interrogate.pack import Pack
from common.models import ASSUMPTION, DECISION, GAP_SEED, Answer, Insight, Question


def _source_refs(question: Question, pack: Pack) -> list[str]:
    if question.applies_to:
        return [question.applies_to]
    primary = pack.grounded[0].id if pack.grounded else pack.seed
    return [primary] if primary else []


def _statement(question: Question, chosen: str) -> str:
    return f"{question.question.rstrip('?')} → {chosen}"


def _rejected(question: Question, chosen_option: str) -> list[str]:
    # INT-05: only an option pick rejects the others; a free-text/option-less answer rejects nothing.
    if not chosen_option:
        return []
    return [o["label"] for o in question.options if o.get("label") and o["label"] != chosen_option]


def distill_answer(answer: Answer, question: Question, pack: Pack, *, run_id: str = "", now: str = "") -> Insight:
    chosen = answer.chosen_option or answer.text
    rejected = _rejected(question, answer.chosen_option)
    return Insight(
        id=f"insight:{pack.context_id}:{question.id}", kind=GAP_SEED if answer.new_seed else DECISION,
        context_id=pack.context_id, question_id=question.id, statement=_statement(question, chosen),
        answered_by=answer.answered_by, confidence="high" if answer.answered_by == "human" else "medium",
        source_refs=_source_refs(question, pack), created_at=now, run_id=run_id,
        rationale=answer.text, rejected=rejected,
    )


def assumption_from_self_answer(question: Question, pack: Pack, *, run_id: str = "", now: str = "") -> Insight:
    return Insight(
        id=f"insight:{pack.context_id}:{question.id}", kind=ASSUMPTION, context_id=pack.context_id,
        question_id=question.id, statement=_statement(question, question.recommendation or "(agent default)"),
        answered_by="agent-self", confidence="low", source_refs=_source_refs(question, pack),
        created_at=now, run_id=run_id,
        rationale="Derived from the pack; surfaced as a vetoable assumption, not a settled decision.",
    )
