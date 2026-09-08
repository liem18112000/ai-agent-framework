"""The opt-in, offline judged eval tier (V2) — semantic rubrics via the provider-sourced judge.

Deliberately SEPARATE from the deterministic default scorer: nothing here runs inside
``evaluate_pack`` / ``evaluate_plan``. Every entry skips cleanly (returns ``None`` / leaves the
report's semantic field ``None``) when the provider is unconfigured or the ``eval`` extra is absent.
"""

from __future__ import annotations

from test_evaluation.eval.judge import build_semantic_judge
from test_evaluation.metrics.rubrics import judge_semantic
from test_evaluation.models import EvalReport, SemanticRubricResult


def score_semantic_rubrics(understanding: str, *, judge=None) -> SemanticRubricResult | None:
    """Run the semantic rubrics through the provider-sourced judge; ``None`` when no judge is
    available (a clean offline skip). Never invoked by the deterministic default path."""
    judge = judge or build_semantic_judge()
    if judge is None:
        return None
    return judge_semantic(understanding, judge)


def attach_semantic(report: EvalReport, understanding: str, *, judge=None) -> EvalReport:
    """Augment a deterministic pack report with the judged semantic rubrics (opt-in). Sets
    ``report.semantic`` (or leaves it ``None`` when no judge). Never called by ``evaluate_pack``."""
    report.semantic = score_semantic_rubrics(understanding, judge=judge)
    return report
