"""ScenarioGen — the flagship implement ``LlmAgent`` (the one default LLM call, I3)."""

from __future__ import annotations

from common.adk import agent_model
from test_plan_definition.llm.adk import build_generator_agent, run_json_agent
from test_plan_definition.llm.prompts import scenarios_prompt
from test_plan_definition.llm.schemas import Scenarios
from test_plan_definition.models import TestData, TestPlan, TestScenario
from test_plan_definition.monitoring import get_logger

log = get_logger("llm.scenarios")

_MAX_TOKENS = 6000


async def claude_scenarios(
    plan: TestPlan, plan_pack, test_data: list[TestData], *, now: str = "", model=None,
) -> list[TestScenario] | None:
    """Structured scenarios via the ScenarioGen ``LlmAgent``; ``None`` (→ heuristic) when unconfigured
    or the model output fails schema validation."""
    model = model or agent_model(max_tokens=_MAX_TOKENS)
    if model is None:
        return None
    agent = build_generator_agent(
        name="tpd_scenario_gen",
        prompt=scenarios_prompt(plan, plan_pack.summary_text(), test_data),
        output_schema=Scenarios, output_key="tpd_scenarios", model=model)
    data = await run_json_agent(agent, output_key="tpd_scenarios")
    if not data:
        log.warning("no scenarios from generator; falling back to heuristic")
        return None
    return Scenarios(**data).to_scenarios(plan, now) or None
