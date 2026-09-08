"""E4 rubric checks — KGA-specific quality gates no off-the-shelf metric knows."""

from __future__ import annotations

import re

from test_evaluation.models import RubricResult, SemanticRubricResult

_JIRA_KEY = re.compile(r"\b[A-Z]{2,}-\d+\b")
_URL = re.compile(r"https?://[^\s)]+")


def cites_only_real_ids(understanding: str, pack_node_ids: set[str]) -> RubricResult:
    """Every Jira key named in the understanding must belong to a pack node. Fabrication guard."""
    mentioned = set(_JIRA_KEY.findall(understanding))
    real = {nid.split(":", 1)[-1].upper() for nid in pack_node_ids if nid.lower().startswith("jira:")}
    invented = sorted(k for k in mentioned if k.upper() not in real)
    return RubricResult(passed=not invented, invented=invented)


def no_invented_urls(understanding: str, pack_text: str) -> RubricResult:
    """Any URL in the understanding must also appear in the pack text (no fabricated links)."""
    invented = sorted({u for u in _URL.findall(understanding) if u not in pack_text})
    return RubricResult(passed=not invented, invented=invented)


SEMANTIC_RUBRICS = {
    "names_the_ac": "Does the understanding state this ticket's actual acceptance criteria "
                    "(not a generic 'high confidence' summary)?",
    "declares_gaps_honestly": "If the pack has declared gaps, does the understanding acknowledge "
                              "the unknowns instead of papering over them?",
}


def judge_semantic(understanding: str, judge) -> SemanticRubricResult:
    """Run each semantic rubric through an injected `judge(question, text) -> bool`."""
    verdicts = {name: bool(judge(q, understanding)) for name, q in SEMANTIC_RUBRICS.items()}
    return SemanticRubricResult(**verdicts)
