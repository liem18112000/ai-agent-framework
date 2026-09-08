"""TestDataGen — the detail-gated implement ``LlmAgent`` for TEST DATA."""

from __future__ import annotations

from common.adk import agent_model
from test_plan_definition.llm.adk import build_generator_agent, run_json_agent
from test_plan_definition.llm.prompts import testdata_prompt
from test_plan_definition.llm.schemas import TestDataList
from test_plan_definition.models import TestData, TestPlan
from test_plan_definition.monitoring import get_logger

log = get_logger("llm.testdata")

_MAX_TOKENS = 6000


async def claude_test_data(
    plan: TestPlan, plan_pack, *, now: str = "", model=None,
) -> list[TestData] | None:
    """Structured test-data via the ``LlmAgent``; ``None`` (→ heuristic) when unconfigured/invalid."""
    model = model or agent_model(max_tokens=_MAX_TOKENS)
    if model is None:
        return None
    agent = build_generator_agent(
        name="tpd_testdata_gen",
        prompt=testdata_prompt(plan, plan_pack.summary_text()),
        output_schema=TestDataList, output_key="tpd_test_data", model=model)
    data = await run_json_agent(agent, output_key="tpd_test_data")
    if not data:
        log.warning("could not parse test-data output; falling back to heuristic")
        return None
    return TestDataList(**data).to_test_data(plan, now) or None
