"""The `adk eval` metric criteria (the test_config.json equivalent).

Deterministic PR gate = custom domain metrics + native trajectory. Judged (nightly) tier adds ADK's
LLM-judged metrics — the semantic-rubric catalog that was declarative-only in v1 finally runs.
"""

from __future__ import annotations

from google.adk.evaluation.eval_metrics import EvalMetric

_CFP = "test_evaluation.eval.adk_metrics"

# --- PR gate: deterministic, no judge model ---
PACK_METRICS = [
    EvalMetric(metric_name="pqs_score", threshold=0.70, custom_function_path=f"{_CFP}.pqs_score"),
    EvalMetric(metric_name="hard_negative_leak", threshold=1.0,
               custom_function_path=f"{_CFP}.hard_negative_leak"),  # threshold 1.0 → FAIL on any leak
]

PLAN_METRICS = [
    EvalMetric(metric_name="tps_score", threshold=0.70, custom_function_path=f"{_CFP}.tps_score"),
    EvalMetric(metric_name="must_not_scope_leak", threshold=1.0,
               custom_function_path=f"{_CFP}.must_not_scope_leak"),
]

# --- Native + judged metrics available in ADK (wired in the nightly tier with a judge model) ---
# Deterministic (no judge): PrebuiltMetrics.TOOL_TRAJECTORY_AVG_SCORE  (replaces v1 trajectory.py).
# Judged (needs a judge model — Claude-via-LiteLlm or Gemini):
#   PrebuiltMetrics.HALLUCINATIONS_V1                         (unsupported-claim detection)
#   PrebuiltMetrics.RUBRIC_BASED_FINAL_RESPONSE_QUALITY_V1    (runs the v1 SEMANTIC_RUBRICS catalog)
#   PrebuiltMetrics.FINAL_RESPONSE_MATCH_V2                   (LLM-judged reference match)
# These skip cleanly when no judge model is configured (mirrors v1 ragas_judge.available()).
NATIVE_TRAJECTORY_METRIC = "tool_trajectory_avg_score"
JUDGED_METRICS = ("hallucinations_v1", "rubric_based_final_response_quality_v1", "final_response_match_v2")
