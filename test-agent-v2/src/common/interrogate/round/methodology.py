"""Methodology define round (TPD): which test methodology (API / E2E / UI) fits this pass."""

from __future__ import annotations

from typing import TYPE_CHECKING

from common.interrogate.pack import Pack
from common.models import Note, Question

if TYPE_CHECKING:
    from common.interrogate.round import QFactory


def build_methodology(pack: Pack, primary: Note | None, title: str, q: QFactory) -> list[Question]:
    applies = primary.id if primary else pack.seed
    return [q(
        question=f"Which test methodology fits '{title}' for this pass?",
        why="Sets what a test even is (a request+assert vs a driven UI flow) and the effort.",
        options=[
            {"label": "API", "implication": "deterministic; no per-step UI detail (POC default)"},
            {"label": "E2E", "implication": "realistic flow; needs step sequences"},
            {"label": "UI", "implication": "highest fidelity; needs detailed UI steps"},
        ],
        recommendation="API — deterministic and enough to prove the loop (POC).",
        applies_to=applies,
    )]
