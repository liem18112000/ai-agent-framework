"""Canonical `AgentEvaluator` harness (E5) — the adk-samples `eval/test_eval.py` entry, factored out."""

from __future__ import annotations

import os
from pathlib import Path

DATA_DIR = Path(__file__).with_name("data")


def creds_available() -> bool:
    """A judge/agent run needs a project — mirror the samples' skip guard."""
    return bool(os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("VERTEX_PROJECT"))


async def run_agent_eval(agent_module: str, *, data_dir: str | Path | None = None, num_runs: int = 2):
    """Run the canonical ADK eval over `agent_module` (e.g. 'knowledge_gathering'). CI-with-creds only."""
    from google.adk.evaluation import AgentEvaluator

    await AgentEvaluator.evaluate(agent_module, str(data_dir or DATA_DIR), num_runs=num_runs)


def judged_available() -> bool:
    """The ADK-native judged tier (V3) is live only with creds AND a provider-sourced judge model
    (its `EvalConfig.criteria` non-empty). Double-gated: `GOOGLE_CLOUD_PROJECT` alone is not enough
    — the judge model comes from `VERTEX_*` via the provider (I8)."""
    from test_evaluation.eval.config import judged_criteria

    return creds_available() and bool(judged_criteria())


async def run_judged_eval(agent_module: str, eval_set, *, num_runs: int = 2):
    """Run the ADK-native judged tier (`JUDGED_METRICS`) over `agent_module` via ADK's own
    LLM-judged evaluators — an opt-in tier, NOT the deterministic default. The judge model is
    provider-sourced (I8). Returns `None` (a clean skip) when creds / the provider are absent, so
    it runs only with creds and skips offline."""
    from test_evaluation.eval.config import judged_criteria

    criteria = judged_criteria()
    if not (creds_available() and criteria):
        return None

    from google.adk.evaluation import AgentEvaluator
    from google.adk.evaluation.eval_config import EvalConfig

    await AgentEvaluator.evaluate_eval_set(
        agent_module, eval_set, eval_config=EvalConfig(criteria=criteria), num_runs=num_runs)
    return True
