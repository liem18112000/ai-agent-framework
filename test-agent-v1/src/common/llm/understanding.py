"""Claude-on-Vertex restatement of the agent's current understanding.

The LLM half of the understanding step: build the prompt, call Vertex, return the prose
brief. Confidence, the heuristic fallback, and orchestration live in refine/understanding.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from common.llm.prompts import understanding_prompt
from common.llm.vertex import complete
from common.models import Insight, Question

if TYPE_CHECKING:  # annotation-only; importing refine.pack at runtime would cycle back into llm
    from common.interrogate.pack import Pack


def claude_understanding(
    pack: Pack,
    insights: list[Insight],
    open_questions: list[Question],
    deferred: list[Question],
    confidence: str,
    *,
    project: str,
    location: str,
    model: str,
) -> str:
    prompt = understanding_prompt(pack, insights, open_questions, confidence)
    return complete(prompt, project=project, location=location, model=model, max_tokens=700).strip() + "\n"
