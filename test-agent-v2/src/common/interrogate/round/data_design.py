"""Data-design implement round: the test-data strategy — valid/invalid partitions + boundary values,
fixtures, and which dependencies are stubbed vs hit for real."""

from __future__ import annotations

from typing import TYPE_CHECKING

from common.interrogate.pack import Pack
from common.models import Note, Question

if TYPE_CHECKING:
    from common.interrogate.round import QFactory


def build_data_design(pack: Pack, primary: Note | None, title: str, q: QFactory) -> list[Question]:
    applies = primary.id if primary else pack.seed
    return [
        q(
            question=f"Test-data partitions for '{title}': which valid + invalid classes and "
                     "boundary values must the data cover?",
            why="Equivalence classes + boundaries are what make the case count reach 100%; vague "
                "'some valid data' misses the edges where defects cluster.",
            options=[
                {"label": "Valid + each invalid class + boundaries",
                 "implication": "full partition coverage (recommended)"},
                {"label": "Valid + headline invalid only", "implication": "faster; misses edges"},
            ],
            recommendation="Valid + each invalid class + the min/empty/max boundaries.",
            applies_to=applies,
        ),
        q(
            question="Which dependencies are stubbed vs hit for real, and what fixtures are needed?",
            why="Decides executability and flakiness of the generated data.",
            options=[
                {"label": "Stub third-party, hit owned datastores",
                 "implication": "deterministic + realistic (recommended)"},
                {"label": "Stub everything", "implication": "deterministic; least realistic"},
            ],
            recommendation="Stub third-party side-effects; hit owned datastores for real.",
            applies_to=applies,
        ),
    ]
