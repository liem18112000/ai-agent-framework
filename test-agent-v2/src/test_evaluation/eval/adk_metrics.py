"""Domain metrics as ADK custom-metric functions (Plan B)."""

from __future__ import annotations

from google.adk.evaluation.eval_metrics import EvalMetric, EvalStatus
from google.adk.evaluation.evaluator import EvaluationResult, PerInvocationResult

from common.memory.factory import build_bank
from test_evaluation.engine import evaluate_pack, evaluate_plan
from test_evaluation.golden import golden_for, golden_plan_for

_BANK = None


def set_bank(bank) -> None:
    """Inject the bank the metrics read (tests). Unset → build_bank() from env."""
    global _BANK
    _BANK = bank


def _bank():
    return _BANK if _BANK is not None else build_bank()


def _ctx(actual_invocations) -> str:
    content = getattr(actual_invocations[0], "user_content", None)
    for part in (getattr(content, "parts", None) or []):
        if getattr(part, "text", None):
            return part.text.strip()
    return ""


def _result(metric: EvalMetric, score, actual, expected) -> EvaluationResult:
    status = EvalStatus.PASSED if (score is not None and score >= metric.threshold) else EvalStatus.FAILED
    pir = PerInvocationResult(actual_invocation=actual[0],
                              expected_invocation=(expected[0] if expected else None),
                              score=score, eval_status=status)
    return EvaluationResult(overall_score=score, overall_eval_status=status, per_invocation_results=[pir])


def _pack(actual):
    ctx = _ctx(actual)
    return evaluate_pack(_bank(), ctx, golden_for(ctx))


def _plan(actual):
    ctx = _ctx(actual)
    return evaluate_plan(_bank(), ctx, golden_plan_for(ctx))


def pqs_score(metric: EvalMetric, actual, expected=None, scenario=None) -> EvaluationResult:
    return _result(metric, _pack(actual).pqs, actual, expected)


def hard_negative_leak(metric: EvalMetric, actual, expected=None, scenario=None) -> EvaluationResult:
    return _result(metric, 0.0 if _pack(actual).retrieval.leaked else 1.0, actual, expected)


def tps_score(metric: EvalMetric, actual, expected=None, scenario=None) -> EvaluationResult:
    return _result(metric, _plan(actual).tps, actual, expected)


def must_not_scope_leak(metric: EvalMetric, actual, expected=None, scenario=None) -> EvaluationResult:
    return _result(metric, 0.0 if _plan(actual).scope.leaked else 1.0, actual, expected)
