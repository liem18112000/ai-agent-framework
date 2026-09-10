"""Generate the clarifying questions for one define round (methodology | scope | metrics)."""

from __future__ import annotations

from collections.abc import Callable

from common.interrogate.pack import Pack
from common.interrogate.questions import build_round_questions
from common.llm.parse import coerce_str, loads_array
from common.llm.vertex import complete, vertex_config
from common.models import Question
from common.testplan.llm.prompts import question_prompt
from common.testplan.models import ROUND_PREFIX as _PREFIX
from test_plan_definition.monitoring import get_logger

log = get_logger("define.questions")

Generator = Callable[[Pack, str], list[Question]]

_FIELDS = ("id", "round", "question", "why", "options", "recommendation",
           "depends_on", "applies_to", "status", "confidence")


def make_generator(understanding: str = "") -> Generator:
    """Select the generator: Claude-on-Vertex when VERTEX_* is configured, else the heuristic."""
    cfg = vertex_config()
    if not cfg:
        return lambda pack, round_name: heuristic_questions(pack, round_name)
    proj, loc, model = cfg

    def generator(pack: Pack, round_name: str) -> list[Question]:
        raw = complete(question_prompt(pack.summary_text(), understanding, round_name),
                       project=proj, location=loc, model=model, max_tokens=6000)
        qs: list[Question] = []
        for it in loads_array(raw) or []:
            it.setdefault("round", round_name)
            if "applies_to" in it:
                it["applies_to"] = coerce_str(it["applies_to"])
            qs.append(Question(**{k: it.get(k) for k in _FIELDS if k in it}))
        if not qs:
            log.warning("round %s: no/invalid LLM questions — using heuristic fallback", round_name)
            qs = heuristic_questions(pack, round_name)
        return qs

    return generator


def heuristic_questions(pack: Pack, round_name: str) -> list[Question]:
    """Derive plan judgement-calls from the pack via the shared interrogation scaffolding."""
    return build_round_questions(pack, round_name, id_prefix=_PREFIX[round_name])
