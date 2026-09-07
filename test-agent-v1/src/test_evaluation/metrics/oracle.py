"""Oracle Strength — would a step actually catch a regression? (deterministic proxy for mutation)

A test that asserts only a status code kills almost no mutant; one that asserts a concrete
end-state kills many. This classifies each step's `expected` text without running anything — a
strong predictor of mutation score, available now (real mutation is gated on the execution stage):
  - weak    — a status code / acceptance only ("2xx", "a 4xx status is returned", "is processed").
  - strong  — names a concrete, resolvable end-state: an ALL-CAPS enum/state token, or a golden
              pass-criterion phrase (e.g. CREDIT_CARD_CHARGED_PENDING).
  - medium  — a resolved metric string that is real prose but not a concrete named state.
score = weighted mean (strong 1.0 / medium 0.5 / weak 0.0). This encodes the execution-depth gap.
"""

from __future__ import annotations

import re

from test_evaluation.models import OracleScore

_WEAK = ("2xx", "3xx", "4xx", "5xx", "status", "accepted", "succeeds", "is returned",
         "is processed", "is ready", "unchanged", "without error", "is rejected")
_ENUM = re.compile(r"[A-Z][A-Z0-9_]{3,}")  # a named state/enum: CREDIT_CARD_CHARGED_PENDING
_WEIGHT = {"strong": 1.0, "medium": 0.5, "weak": 0.0}


def classify(expected: str, pass_criteria: tuple[str, ...] = ()) -> str:
    low = expected.lower()
    if _ENUM.search(expected) or any(p and p.lower() in low for p in pass_criteria):
        return "strong"
    if any(w in low for w in _WEAK):
        return "weak"
    return "medium"


def oracle_strength(steps: list[dict], pass_criteria: tuple[str, ...] = ()) -> OracleScore:
    """Score the `expected` of each step. Steps with no `expected` are ignored (nothing asserted)."""
    graded = [(e, classify(e, pass_criteria)) for s in steps if (e := s.get("expected"))]
    dist = {k: sum(t == k for _, t in graded) for k in ("strong", "medium", "weak")}
    score = sum(_WEIGHT[t] for _, t in graded) / len(graded) if graded else 0.0
    return OracleScore(round(score, 3), dist, sorted({e for e, t in graded if t == "weak"}))
