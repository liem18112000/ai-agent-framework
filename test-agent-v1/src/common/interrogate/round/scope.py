"""Scope define round (TPD): is the feature the full test scope + recorded-only integrations."""

from __future__ import annotations

from common.interrogate.pack import Pack
from common.interrogate.round.base import QFactory, RoundQuestions
from common.models import Note, Question


class ScopeRound(RoundQuestions):
    round = "scope"

    def build(self, pack: Pack, primary: Note | None, title: str, q: QFactory) -> list[Question]:
        applies = primary.id if primary else pack.seed
        out = [q(
            question=f"Is '{title}' the full test scope, or are its integration points also in scope?",
            why="Out-of-scope-for-gathering is not out-of-scope-for-testing; this bounds the suite.",
            options=[
                {"label": "In scope", "implication": "test this feature/service only"},
                {"label": "Out of scope", "implication": "exclude and record the assumption"},
            ],
            recommendation="In scope — the feature under test.",
            applies_to=applies,
        )]
        for t in pack.recorded_only_types():
            out.append(q(
                question=f"The pack records but did not follow {t} link(s) — is {t} in test scope?",
                why="A load-bearing integration left untested silently narrows coverage.",
                options=[
                    {"label": "In scope", "implication": f"add {t} coverage"},
                    {"label": "Out of scope", "implication": f"exclude {t}; record the assumption"},
                ],
                recommendation=f"Confirm whether {t} is load-bearing for '{title}'.",
                applies_to=t,
            ))
        return out
