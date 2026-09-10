"""Rank and cap the clarifying questions for one interrogation round."""

from __future__ import annotations

from collections.abc import Callable

from common.interrogate.pack import Pack
from common.interrogate.round import RoundQuestions
from common.llm.questions import claude_questions
from common.models import Question
from common.monitoring import get_logger

log = get_logger("interrogate.questions")

Generator = Callable[[Pack, str], list[Question]]


def generate_round(pack: Pack, round_name: str, *, max_questions: int = 7, generator: Generator | None = None) -> list[Question]:
    generator = generator or make_generator()
    questions = _rank([q for q in generator(pack, round_name) if q.round == round_name])
    _defer_excess_open(questions, max_questions)
    log.info(
        "round %s: %d questions (%d open, %d self-answered)", round_name, len(questions),
        sum(q.status == "open" for q in questions), sum(q.status == "self-answered" for q in questions),
    )
    return questions


def _rank(questions: list[Question]) -> list[Question]:
    """Stable topological-ish order: a question follows the ones it depends on."""
    by_id = {q.id: q for q in questions}
    placed: list[Question] = []
    seen: set[str] = set()
    remaining = list(questions)
    while remaining:
        progressed = False
        for q in list(remaining):
            if all(dep not in by_id or dep in seen for dep in q.depends_on):
                placed.append(q)
                seen.add(q.id)
                remaining.remove(q)
                progressed = True
        if not progressed:
            placed.extend(remaining)
            break
    return placed


def _defer_excess_open(questions: list[Question], cap: int) -> None:
    """Keep the first `cap` open questions open; defer the rest (flagged, not dropped)."""
    seen_open = 0
    for q in questions:
        if q.status == "open":
            seen_open += 1
            if seen_open > cap:
                q.status = "deferred"


def make_generator() -> Generator:
    # Lazy: common.adk.model → common.adk imports common.interrogate (this package) — a top-level
    # import would cycle. Deferred to call time (see common.llm.questions for the same rationale).
    from common.adk.model import model_configured

    if model_configured():

        def generator(pack: Pack, round_name: str) -> list[Question]:
            qs = claude_questions(pack, round_name)
            if not qs:
                log.warning("round %s: LLM returned no questions — using heuristic fallback", round_name)
                qs = heuristic_questions(pack, round_name)
            return qs

        return generator
    return heuristic_questions


def build_round_questions(pack: Pack, round_name: str, *, id_prefix: str) -> list[Question]:
    """Dispatch to the registered RoundQuestions strategy with a q-factory that stamps ids."""
    primary = pack.grounded[0] if pack.grounded else None
    title = primary.title if primary else (pack.seed or pack.context_id)
    n = 0

    def q(**kw) -> Question:
        nonlocal n
        n += 1
        kw.setdefault("id", f"Q-{id_prefix}-{n}")
        kw.setdefault("round", round_name)
        return Question(**kw)

    strategy = RoundQuestions.registry.get(round_name)
    return strategy.build(pack, primary, title, q) if strategy else []


def heuristic_questions(pack: Pack, round_name: str) -> list[Question]:
    """KGA refine rounds (business/technical/qa); id prefix is the round's first 3 letters."""
    return build_round_questions(pack, round_name, id_prefix=round_name[:3])
