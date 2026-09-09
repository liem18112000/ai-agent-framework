"""Claude-on-Vertex generators for the define stage — round questions and the plan brief."""

from __future__ import annotations

from common.llm.parse import coerce_str, loads_array
from common.llm.vertex import complete
from common.models import Question
from common.testplan.llm.prompts import brief_prompt, question_prompt
from common.testplan.models import TestPlan
from test_plan_definition.monitoring import get_logger

log = get_logger("llm.define")

_FIELDS = ("id", "round", "question", "why", "options", "recommendation",
           "depends_on", "applies_to", "status", "confidence")


def claude_plan_questions(pack, understanding: str, round_name: str, *,
                          project: str, location: str, model: str) -> list[Question]:
    raw = complete(question_prompt(pack.summary_text(), understanding, round_name),
                   project=project, location=location, model=model, max_tokens=6000)
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


def claude_brief(plan: TestPlan, plan_pack, open_questions: list[Question], *,
                 project: str, location: str, model: str) -> str:
    prompt = brief_prompt(plan, plan_pack.summary_text(), [q.question for q in open_questions])
    return complete(prompt, project=project, location=location, model=model,
                    max_tokens=700).strip() + "\n"
