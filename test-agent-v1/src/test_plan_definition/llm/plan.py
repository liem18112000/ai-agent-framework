"""Claude-on-Vertex restatement of the proposed Test Plan brief.

Confidence, TestPlan assembly, and the heuristic fallback live in define/plan.py; this is
just the prose. Mirrors common.llm.understanding.
"""

from __future__ import annotations

from common.llm.vertex import complete
from common.models import Question
from test_plan_definition.llm.prompts import brief_prompt
from test_plan_definition.models import TestPlan


def claude_brief(
    plan: TestPlan, plan_pack, open_questions: list[Question], *,
    project: str, location: str, model: str,
) -> str:
    prompt = brief_prompt(plan, plan_pack.summary_text(), [q.question for q in open_questions])
    return complete(prompt, project=project, location=location, model=model, max_tokens=700).strip() + "\n"
