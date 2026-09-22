"""Technical interrogation round (KGA refine): target environment + recorded-only link types."""

from __future__ import annotations

from typing import TYPE_CHECKING

from common.interrogate.pack import Pack
from common.models import Note, Question

if TYPE_CHECKING:
    from common.interrogate.round import QFactory


def build_technical(pack: Pack, primary: Note | None, title: str, q: QFactory) -> list[Question]:
    out = [q(
        question="Which environment/tenant should the tests target?",
        why="Determines data setup, credentials, and blast radius.",
        options=[
            {"label": "dev tenant", "implication": "safe default; may lack prod-like data"},
            {"label": "test tenant", "implication": "closer to real; more setup"},
        ],
        recommendation="dev tenant by default.",
        applies_to=primary.id if primary else pack.seed,
    )]
    for t in pack.recorded_only_types():
        out.append(q(
            question=f"The pack records but did not follow {t} link(s) — is {t} behaviour in "
                     "test scope, and which module owns it?",
            why="Out-of-scope-for-gathering does not mean out-of-scope-for-testing.",
            options=[
                {"label": "In scope", "implication": f"add {t} coverage; needs its owner"},
                {"label": "Out of scope", "implication": "record the assumption and skip"},
            ],
            recommendation=f"Confirm whether {t} is load-bearing for this feature.",
        ))
    return out
