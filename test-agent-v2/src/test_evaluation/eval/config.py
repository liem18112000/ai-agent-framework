"""The `adk eval` metric criteria (the test_config.json equivalent)."""

from __future__ import annotations

from google.adk.evaluation.eval_metrics import EvalMetric

_CFP = "test_evaluation.eval.adk_metrics"

PACK_METRICS = [
    EvalMetric(metric_name="pqs_score", threshold=0.70, custom_function_path=f"{_CFP}.pqs_score"),
    EvalMetric(metric_name="hard_negative_leak", threshold=1.0,
               custom_function_path=f"{_CFP}.hard_negative_leak"),
]

PLAN_METRICS = [
    EvalMetric(metric_name="tps_score", threshold=0.70, custom_function_path=f"{_CFP}.tps_score"),
    EvalMetric(metric_name="must_not_scope_leak", threshold=1.0,
               custom_function_path=f"{_CFP}.must_not_scope_leak"),
]

NATIVE_TRAJECTORY_METRIC = "tool_trajectory_avg_score"
JUDGED_METRICS = ("hallucinations_v1", "rubric_based_final_response_quality_v1", "final_response_match_v2")
