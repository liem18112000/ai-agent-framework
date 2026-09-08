"""Data contracts for the self-learning package."""

from __future__ import annotations

from dataclasses import dataclass, field

from common.models import LESSON


@dataclass
class LessonSignal:
    """A candidate lesson from a step, pre-distillation."""

    statement: str
    kind: str = LESSON
    source_refs: list[str] = field(default_factory=list)
    confidence: str = "low"
    rationale: str = ""
