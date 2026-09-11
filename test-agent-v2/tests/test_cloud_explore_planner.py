"""X5 cloud-explore sub-agent — the `CloudExplorePlan` output_schema + the `LlmAgent` planner (fake
model), and the heuristic (no-Vertex) fallback (numeric rank, empty plan = identity)."""

from __future__ import annotations

import json

from common.cloud import SERVERLESS, ServiceRef
from knowledge_gathering.gather.explore.planners.cloud_explore import (
    OUTPUT_KEY,
    build_cloud_explore_agent,
)
from knowledge_gathering.gather.explore.planners.schemas import CloudExplorePlan
from knowledge_gathering.gather.explore.seeds.cloud_discover import rerank_with_plan
from tests.conftest import fake_model, run_planner_agent


async def test_agent_writes_validated_plan_to_state():
    canned = json.dumps({"priority_services": ["luz-thumbnail", "luz-docs"],
                         "clusters": [["luz-thumbnail"]]})
    model = fake_model(canned)
    agent = build_cloud_explore_agent(model=model)
    state = await run_planner_agent(
        agent, {"title": "Thumbnails fail", "description": "d", "labels": ["media"]},
        output_key=OUTPUT_KEY)
    assert CloudExplorePlan(**state).hints() == ["luz-thumbnail", "luz-docs"]
    assert len(model.calls) == 1


async def test_agent_empty_object_yields_no_hints():
    agent = build_cloud_explore_agent(model=fake_model("{}"))
    state = await run_planner_agent(agent, {"title": "t", "description": "", "labels": []},
                                    output_key=OUTPUT_KEY)
    assert CloudExplorePlan(**state).hints() == []


def test_hints_dedup_lowercase_and_capped():
    plan = CloudExplorePlan(priority_services=["Luz-Docs", "luz-docs", *[f"s{i}" for i in range(15)]])
    hints = plan.hints()
    assert hints[0] == "luz-docs" and hints.count("luz-docs") == 1
    assert len(hints) == 12                     # _MAX_CLOUD_HINTS


def test_heuristic_fallback_is_numeric_rank_when_no_plan():
    """Without Vertex the planner is a no-op → cloud_plan is None → discover ranks numerically; an empty
    plan applied to the ranked list is the identity (the same numeric order)."""
    ranked = [ServiceRef("gcp", "prod", SERVERLESS, "a"), ServiceRef("gcp", "dev", SERVERLESS, "b")]
    assert rerank_with_plan(CloudExplorePlan(), ranked) == ranked
