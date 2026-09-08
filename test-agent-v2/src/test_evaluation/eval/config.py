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

JUDGED_THRESHOLD = 0.70


def judged_criteria() -> dict:
    """The ADK-native judged tier (V3) as an `EvalConfig.criteria` map — ADK's own LLM-judged
    evaluators (`JUDGED_METRICS`) instead of a bespoke path, with `SEMANTIC_RUBRICS` mapped onto
    `rubric_based_final_response_quality_v1`.

    The judge model is provider-sourced (I8, via `judge_model_id()`), never OpenAI or any other default.
    Returns an empty dict — a clean skip — when the provider is unconfigured (no `VERTEX_*`), so
    the offline suite never wires (nor runs) the judged tier. Heavy ADK imports are lazy so the
    module stays import-light and offline-safe.
    """
    from test_evaluation.eval.judge import judge_model_id

    model = judge_model_id()
    if model is None:
        return {}

    from google.adk.evaluation.eval_metrics import (
        HallucinationsCriterion,
        JudgeModelOptions,
        LlmAsAJudgeCriterion,
        RubricsBasedCriterion,
    )
    from google.adk.evaluation.eval_rubrics import Rubric, RubricContent

    from test_evaluation.metrics.rubrics import SEMANTIC_RUBRICS

    opts = JudgeModelOptions(judge_model=model)
    rubrics = [
        Rubric(rubric_id=name, rubric_content=RubricContent(text_property=text))
        for name, text in SEMANTIC_RUBRICS.items()
    ]
    return {
        "hallucinations_v1": HallucinationsCriterion(
            threshold=JUDGED_THRESHOLD, judge_model_options=opts),
        "rubric_based_final_response_quality_v1": RubricsBasedCriterion(
            threshold=JUDGED_THRESHOLD, judge_model_options=opts, rubrics=rubrics),
        "final_response_match_v2": LlmAsAJudgeCriterion(
            threshold=JUDGED_THRESHOLD, judge_model_options=opts),
    }
