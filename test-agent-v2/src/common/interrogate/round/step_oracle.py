"""Step-oracle implement round: the ORACLE each case asserts (status vs end-state vs side-effect) plus
teardown and negative assertions — what makes a step meaningfully verify, not just `assert 200`."""

from __future__ import annotations

from typing import TYPE_CHECKING

from common.interrogate.pack import Pack
from common.models import Note, Question

if TYPE_CHECKING:
    from common.interrogate.round import QFactory


def build_step_oracle(pack: Pack, primary: Note | None, title: str, q: QFactory) -> list[Question]:
    return [q(
        question=f"What is the ORACLE for '{title}' — how does a step decide pass/fail?",
        why="`assert 200` proves the call was accepted, not that it was correct; the oracle is "
            "what actually catches bugs.",
        options=[
            {"label": "End-state / side-effect",
             "implication": "assert the stored field / counter / emitted event (recommended)"},
            {"label": "Response body + status", "implication": "assert the returned payload shape"},
            {"label": "Status only", "implication": "shallow; misses wrong-but-200 bugs"},
        ],
        recommendation="End-state / side-effect — assert the real observable the pack names, and "
                       "for negative/error cases assert NO side effect + a consistent end state.",
        applies_to=primary.id if primary else pack.seed,
    )]
