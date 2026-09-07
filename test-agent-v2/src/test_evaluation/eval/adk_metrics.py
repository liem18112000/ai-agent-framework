"""Domain metrics as ADK custom-metric functions (Plan B).

Each has ADK's custom-metric signature `(EvalMetric, actual_invocations, expected_invocations,
conversation_scenario) -> EvaluationResult` and is loadable by dotted path via ADK's
`custom_metric_evaluator`. They wrap the UNCHANGED v1 engine (`engine.evaluate_pack` /
`plan_engine.evaluate_plan`), so the numbers reproduce by construction while `google-adk`'s eval
types (EvaluationResult / PerInvocationResult / EvalMetric / Invocation) are genuinely on-path.

The context id is read from the invocation's user_content; the bank is injected in tests via
`set_bank`, else built from env (as `adk eval` would at runtime).
"""

from __future__ import annotations

from google.adk.evaluation.eval_metrics import EvalMetric, EvalStatus
from google.adk.evaluation.evaluator import EvaluationResult, PerInvocationResult

from common.memory.factory import build_bank
from test_evaluation.engine import evaluate_pack
from test_evaluation.executor.base import golden_for, golden_plan_for
from test_evaluation.plan_engine import evaluate_plan

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


def _result(score, threshold, actual, expected) -> EvaluationResult:
    passed = score is not None and score >= threshold
    status = EvalStatus.PASSED if passed else EvalStatus.FAILED
    pir = PerInvocationResult(
        actual_invocation=actual[0],
        expected_invocation=(expected[0] if expected else None),
        score=score, eval_status=status,
    )
    return EvaluationResult(overall_score=score, overall_eval_status=status,
                            per_invocation_results=[pir])


# --- pack (KGA) --- #
def pqs_score(eval_metric: EvalMetric, actual_invocations, expected_invocations=None,
              conversation_scenario=None) -> EvaluationResult:
    report = evaluate_pack(_bank(), _ctx(actual_invocations), golden_for(_ctx(actual_invocations)))
    return _result(report.pqs, eval_metric.threshold, actual_invocations, expected_invocations)


def hard_negative_leak(eval_metric: EvalMetric, actual_invocations, expected_invocations=None,
                       conversation_scenario=None) -> EvaluationResult:
    report = evaluate_pack(_bank(), _ctx(actual_invocations), golden_for(_ctx(actual_invocations)))
    score = 0.0 if report.retrieval.leaked else 1.0  # threshold 1.0 → FAIL on any leak
    return _result(score, eval_metric.threshold, actual_invocations, expected_invocations)


# --- plan (TPD) --- #
def tps_score(eval_metric: EvalMetric, actual_invocations, expected_invocations=None,
              conversation_scenario=None) -> EvaluationResult:
    report = evaluate_plan(_bank(), _ctx(actual_invocations), golden_plan_for(_ctx(actual_invocations)))
    return _result(report.tps, eval_metric.threshold, actual_invocations, expected_invocations)


def must_not_scope_leak(eval_metric: EvalMetric, actual_invocations, expected_invocations=None,
                        conversation_scenario=None) -> EvaluationResult:
    report = evaluate_plan(_bank(), _ctx(actual_invocations), golden_plan_for(_ctx(actual_invocations)))
    score = 0.0 if report.scope.leaked else 1.0
    return _result(score, eval_metric.threshold, actual_invocations, expected_invocations)
