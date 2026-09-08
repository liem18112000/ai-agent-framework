"""Claude-on-Vertex generator for one interrogation round's clarifying questions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from common.llm.parse import coerce_str, loads_array
from common.llm.prompts import question_prompt
from common.llm.vertex import complete
from common.models import Question
from common.monitoring import get_logger

if TYPE_CHECKING:
    from common.interrogate.pack import Pack

log = get_logger("llm.questions")

_FIELDS = (
    "id", "round", "question", "why", "options", "recommendation",
    "depends_on", "applies_to", "status", "confidence",
)


def claude_questions(
    pack: Pack, round_name: str, *, project: str, location: str, model: str
) -> list[Question]:
    raw = complete(
        question_prompt(pack, round_name),
        project=project, location=location, model=model, max_tokens=6000,
    )
    return _parse(raw, round_name)


def _parse(raw: str, round_name: str) -> list[Question]:
    items = loads_array(raw)
    if items is None:
        log.warning("round %s: could not parse generator output as JSON", round_name)
        return []
    out = []
    for it in items:
        it.setdefault("round", round_name)
        if "applies_to" in it:
            it["applies_to"] = coerce_str(it["applies_to"])
        out.append(Question(**{k: it.get(k) for k in _FIELDS if k in it}))
    return out
