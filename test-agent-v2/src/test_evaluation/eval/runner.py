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
