"""Claude-on-Vertex restatement of the agent's current understanding."""

from __future__ import annotations

from typing import TYPE_CHECKING

from common.llm.prompts import understanding_prompt
from common.models import Insight, Question

if TYPE_CHECKING:
    from common.interrogate.pack import Pack


def claude_understanding(
    pack: Pack, insights: list[Insight], open_questions: list[Question], deferred: list[Question],
    confidence: str,
) -> str:
    # Lazy import — see common.llm.questions.claude_questions for the cycle rationale.
    from common.adk.model import complete

    return complete(understanding_prompt(pack, insights, open_questions, confidence),
                    max_tokens=700).strip() + "\n"
