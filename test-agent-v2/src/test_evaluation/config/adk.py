"""ADK-native eval metric criteria + thresholds — the `test_config.json` equivalents.

Data only (no logic): `eval/config.py` builds the ADK `EvalConfig`/`EvalMetric` objects from these, and
`eval/evalset.py` writes `TEST_CONFIG` out as the deterministic PR-gate criteria file."""

from __future__ import annotations

# The ADK-native trajectory metric (exact tool-order match) used by the deterministic tier.
NATIVE_TRAJECTORY_METRIC = "tool_trajectory_avg_score"

# The judged (LLM-graded) ADK metrics run in the nightly `[eval]` tier + their shared pass threshold.
JUDGED_METRICS = ("hallucinations_v1", "rubric_based_final_response_quality_v1", "final_response_match_v2")
JUDGED_THRESHOLD = 0.70

# The deterministic `adk eval` criteria file: exact tool trajectory + a response ROUGE floor.
TEST_CONFIG = {"criteria": {"tool_trajectory_avg_score": 1.0, "response_match_score": 0.35}}
