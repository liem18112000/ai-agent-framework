"""Data contracts for the self-learning package."""

from __future__ import annotations

from dataclasses import dataclass, field

from common.models import LESSON


@dataclass
class LessonSignal:
    """A candidate lesson from a step, pre-distillation."""

    statement: str
    kind: str = LESSON  # lesson | correction | gotcha
    source_refs: list[str] = field(default_factory=list)  # node ids that ground it
    confidence: str = "low"  # high=human · medium · low=agent-derived
    rationale: str = ""
