"""Case-design implement round: which test KINDS to cover (open taxonomy — the user may add more) and
how deep, applying the plan's chosen test-design method. Distils into the plan's `test_kinds`."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from common.interrogate.pack import Pack
from common.models import Note, Question

if TYPE_CHECKING:
    from common.interrogate.round import QFactory

# The default kinds are only a seed; the question invites the user to ADD any others.
DEFAULT_KINDS = ["happy", "negative", "boundary", "error"]
EXTRA_KINDS = ["security", "performance", "concurrency", "compliance", "accessibility",
               "i18n", "migration", "resilience"]


def build_case_design(pack: Pack, primary: Note | None, title: str, q: QFactory) -> list[Question]:
    return [q(
        question=f"Which test KINDS should '{title}' cover? Start from happy/negative/boundary/"
                 "error and ADD any this feature needs (security, performance, concurrency, "
                 "compliance, accessibility, i18n, migration…). Cases per kind are uncapped — "
                 "aim to cover 100%.",
        why="The kind set is open, not a fixed four; missing a category (e.g. security) means the "
            "suite can never cover that logic.",
        options=[
            {"label": "happy, negative, boundary, error", "implication": "the functional default"},
            {"label": "+ security", "implication": "add auth/authz/injection cases (risk features)"},
            {"label": "+ performance", "implication": "add load/latency cases (hot paths)"},
            {"label": "+ concurrency", "implication": "add idempotency/race cases (stateful writes)"},
        ],
        recommendation="happy, negative, boundary, error — plus security/performance/concurrency "
                       "where the pack shows auth, hot paths or shared state.",
        applies_to=primary.id if primary else pack.seed,
    )]


def kinds_from_answer(chosen: str) -> list[str]:
    """Parse the chosen/added kinds out of a case-design answer into an ordered, deduped list.
    Recognises the default four plus the known extras; falls back to the defaults when none match."""
    low = chosen.lower()
    # whole-word match, and drop a kind the user negated ("no negative", "not performance")
    found = [k for k in [*DEFAULT_KINDS, *EXTRA_KINDS]
             if re.search(rf"(?<!no )(?<!not )\b{k}\b", low)]
    # a bare "+ security" style answer implies the defaults too
    if any(k in EXTRA_KINDS for k in found) and not all(k in low for k in DEFAULT_KINDS):
        found = list(dict.fromkeys([*DEFAULT_KINDS, *found]))
    return found or DEFAULT_KINDS
