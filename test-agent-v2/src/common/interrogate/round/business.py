"""Business interrogation round (KGA refine): what 'done' means + unreachable sources of truth."""

from __future__ import annotations

from typing import TYPE_CHECKING

from common.interrogate.pack import Pack
from common.models import Note, Question

if TYPE_CHECKING:
    from common.interrogate.round import QFactory


def build_business(pack: Pack, primary: Note | None, title: str, q: QFactory) -> list[Question]:
    out = [q(
        question=f"What does 'done' mean for '{title}' — the action is accepted, or the end "
                 "state is fully materialized and verifiable?",
        why="Sets the pass/fail assertion for the whole test and the evaluation metric.",
        options=[
            {"label": "Accepted", "implication": "faster; misses downstream failures"},
            {"label": "Fully materialized", "implication": "true end-state; needs deeper checks"},
        ],
        recommendation="Fully materialized — assert the real end state.",
        applies_to=primary.id if primary else pack.seed,
    )]
    for gap in pack.gaps:
        out.append(q(
            question=f"Source '{gap}' was unreachable during gathering — is it the source of "
                     "truth for this work, or superseded?",
            why="An unread source of truth would silently narrow scope.",
            options=[
                {"label": "Source of truth", "implication": "re-seed gathering to read it"},
                {"label": "Superseded", "implication": "record as out of scope and move on"},
            ],
            recommendation="Re-seed and read it before deciding scope.",
            applies_to=gap,
        ))
    return out
