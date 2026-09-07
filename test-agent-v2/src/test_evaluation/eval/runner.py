"""Canonical `AgentEvaluator` harness (E5) — the adk-samples `eval/test_eval.py` entry, factored out.

`AgentEvaluator.evaluate(agent, data_dir, num_runs)` RUNS the agent against the evalset and scores it
with the `test_config.json` criteria — so it needs the agent's REAL services (GCS / Vertex /
Atlassian); it does not use the offline FakeBucket. Hence this is a **creds-gated CI harness**, not an
offline unit test. Offline reproduction of the composite scores (PQS/TPS) lives in
`tests/test_adk_eval.py` via the custom-metric functions.
"""

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
