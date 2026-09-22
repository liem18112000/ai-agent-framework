"""QA interrogation round (KGA refine): coverage bar + test-data/externals strategy."""

from __future__ import annotations

from typing import TYPE_CHECKING

from common.interrogate.pack import Pack
from common.models import Note, Question

if TYPE_CHECKING:
    from common.interrogate.round import QFactory


def build_qa(pack: Pack, primary: Note | None, title: str, q: QFactory) -> list[Question]:
    return [
        q(
            question=f"Coverage bar for '{title}': happy-path only, or + negative/boundary/error?",
            why="Quality-vs-speed judgement; higher-risk areas need more than the happy path.",
            options=[
                {"label": "Happy path only", "implication": "fast; misses failure modes"},
                {"label": "+ negative/boundary", "implication": "catches regressions; more effort"},
            ],
            recommendation="+ negative/boundary for any data-loss/auth/compliance risk.",
            applies_to=primary.id if primary else pack.seed,
        ),
        q(
            question="Test data & externals: which services are stubbed vs hit for real, and what "
                     "fixtures are needed?",
            why="Decides scenario executability and flakiness.",
            options=[
                {"label": "Stub externals", "implication": "deterministic; less realistic"},
                {"label": "Hit real deps", "implication": "realistic; slower, flakier"},
            ],
            recommendation="Stub third-party side-effects; hit owned datastores for real.",
            applies_to=primary.id if primary else pack.seed,
        ),
    ]
