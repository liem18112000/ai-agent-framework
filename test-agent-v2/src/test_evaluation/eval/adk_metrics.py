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
from test_evaluation.golden import golden_for, golden_plan_for
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


def _result(metric: EvalMetric, score, actual, expected) -> EvaluationResult:
    status = EvalStatus.PASSED if (score is not None and score >= metric.threshold) else EvalStatus.FAILED
    pir = PerInvocationResult(actual_invocation=actual[0],
                              expected_invocation=(expected[0] if expected else None),
                              score=score, eval_status=status)
    return EvaluationResult(overall_score=score, overall_eval_status=status, per_invocation_results=[pir])


def _pack(actual):  # ctx computed once (not twice) → one event scan + one golden lookup
    ctx = _ctx(actual)
    return evaluate_pack(_bank(), ctx, golden_for(ctx))


def _plan(actual):
    ctx = _ctx(actual)
    return evaluate_plan(_bank(), ctx, golden_plan_for(ctx))


# Each metric = one scoring rule over the (unchanged v1) engine's report. Threshold 1.0 on a leak
# gate → PASS only when nothing leaked.
def pqs_score(metric: EvalMetric, actual, expected=None, scenario=None) -> EvaluationResult:
    return _result(metric, _pack(actual).pqs, actual, expected)


def hard_negative_leak(metric: EvalMetric, actual, expected=None, scenario=None) -> EvaluationResult:
    return _result(metric, 0.0 if _pack(actual).retrieval.leaked else 1.0, actual, expected)


def tps_score(metric: EvalMetric, actual, expected=None, scenario=None) -> EvaluationResult:
    return _result(metric, _plan(actual).tps, actual, expected)


def must_not_scope_leak(metric: EvalMetric, actual, expected=None, scenario=None) -> EvaluationResult:
    return _result(metric, 0.0 if _plan(actual).scope.leaked else 1.0, actual, expected)
