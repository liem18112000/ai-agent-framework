"""Metrics define round (TPD): what 'passed' means + the coverage bar (self-answered default)."""

from __future__ import annotations

from common.interrogate.pack import Pack
from common.interrogate.round.base import QFactory, RoundQuestions
from common.models import Note, Question


class MetricsRound(RoundQuestions):
    round = "metrics"

    def build(self, pack: Pack, primary: Note | None, title: str, q: QFactory) -> list[Question]:
        applies = primary.id if primary else pack.seed
        return [
            q(
                question=f"What does 'passed' mean for '{title}' — action accepted, or end-state verified?",
                why="This is the pass/fail assertion every scenario is graded against.",
                options=[
                    {"label": "Accepted", "implication": "fast; misses downstream failures"},
                    {"label": "End-state verified", "implication": "true outcome; needs deeper checks"},
                ],
                recommendation="End-state verified — assert the real outcome.",
                applies_to=applies,
            ),
            q(
                question=f"Coverage bar for '{title}': happy-path only, or + negative/boundary?",
                why="Quality-vs-speed judgement; the agent defaults it and surfaces it as an assumption.",
                options=[
                    {"label": "Happy only", "implication": "fast; misses failure modes"},
                    {"label": "+ negative", "implication": "catches regressions; more scenarios"},
                ],
                recommendation="+ negative for any data-loss/auth/compliance risk.",
                status="self-answered",
                confidence="medium",
                applies_to=applies,
            ),
        ]
