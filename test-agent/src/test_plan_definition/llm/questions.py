"""Claude-on-Vertex generator for one define round's questions.

Build the prompt, call Vertex (reusing common.llm.vertex.complete), parse the
JSON reply into `Question`s. Ranking/capping and the heuristic fallback live in
define/questions.py. Mirrors common.llm.questions.
"""

from __future__ import annotations

from common.llm.parse import coerce_str, loads_array
from common.llm.vertex import complete
from common.models import Question
from test_plan_definition.llm.prompts import question_prompt
from test_plan_definition.monitoring import get_logger

log = get_logger("llm.questions")

_FIELDS = (
    "id", "round", "question", "why", "options", "recommendation",
    "depends_on", "applies_to", "status", "confidence",
)


def claude_plan_questions(
    pack, understanding: str, round_name: str, *, project: str, location: str, model: str
) -> list[Question]:
    raw = complete(
        question_prompt(pack.summary_text(), understanding, round_name),
        # 1500 truncated multi-question JSON -> parse failure -> 0 questions (same bug the refine
        # generator had; see common.llm.questions). 6000 fits a full round.
        project=project, location=location, model=model, max_tokens=6000,
    )
    items = loads_array(raw)
    if items is None:
        log.warning("round %s: could not parse generator output as JSON", round_name)
        return []
    out = []
    for it in items:
        it.setdefault("round", round_name)
        if "applies_to" in it:  # LLM sometimes returns a list; the field's contract is str
            it["applies_to"] = coerce_str(it["applies_to"])
        out.append(Question(**{k: it.get(k) for k in _FIELDS if k in it}))
    return out
