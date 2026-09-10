"""Generate the clarifying questions for one define round (methodology | scope | metrics)."""

from __future__ import annotations

from collections.abc import Callable

from common.interrogate.pack import Pack
from common.interrogate.questions import build_round_questions
from common.llm.vertex import vertex_config
from common.models import Question
from common.testplan.models import ROUND_PREFIX as _PREFIX
from test_plan_definition.monitoring import get_logger

log = get_logger("define.questions")

Generator = Callable[[Pack, str], list[Question]]


def make_generator(understanding: str = "") -> Generator:
    """Select the generator: Claude-on-Vertex when VERTEX_* is configured, else the heuristic."""
    cfg = vertex_config()
    if not cfg:
        return lambda pack, round_name: heuristic_questions(pack, round_name)
    proj, loc, model = cfg
    from test_plan_definition.define.llm import claude_plan_questions

    def generator(pack: Pack, round_name: str) -> list[Question]:
        qs = claude_plan_questions(
            pack, understanding, round_name, project=proj, location=loc, model=model)
        if not qs:
            log.warning(
                "round %s: LLM returned no questions — using heuristic fallback", round_name)
            qs = heuristic_questions(pack, round_name)
        return qs

    return generator


def heuristic_questions(pack: Pack, round_name: str) -> list[Question]:
    """Derive plan judgement-calls from the pack via the shared interrogation scaffolding."""
    return build_round_questions(pack, round_name, id_prefix=_PREFIX[round_name])
