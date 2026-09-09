"""Claude-on-Vertex generators for the implement stage — scenarios (the I3 default call), steps,
test-data. Each returns None (→ heuristic fallback) when unconfigured or the output fails schema."""

from __future__ import annotations

from common.adk import agent_model
from test_plan_definition.llm.adk import build_generator_agent, run_json_agent
from test_plan_definition.llm.prompts import scenarios_prompt, steps_prompt, testdata_prompt
from test_plan_definition.llm.schemas import Scenarios, StepsList, TestDataList
from test_plan_definition.models import TestData, TestPlan, TestScenario, TestStep
from test_plan_definition.monitoring import get_logger

log = get_logger("llm.implement")


async def claude_scenarios(plan: TestPlan, plan_pack, test_data: list[TestData], *,
                           now: str = "", model=None) -> list[TestScenario] | None:
    model = model or agent_model(max_tokens=6000)
    if model is None:
        return None
    agent = build_generator_agent(name="tpd_scenario_gen",
                                  prompt=scenarios_prompt(plan, plan_pack.summary_text(), test_data),
                                  output_schema=Scenarios, output_key="tpd_scenarios", model=model)
    data = await run_json_agent(agent, output_key="tpd_scenarios")
    if not data:
        log.warning("no scenarios from generator; falling back to heuristic")
        return None
    return Scenarios(**data).to_scenarios(plan, now) or None


async def claude_steps(scenarios: list[TestScenario], plan: TestPlan, plan_pack, test_data, *,
                       now: str = "", model=None) -> dict[str, list[TestStep]] | None:
    model = model or agent_model(max_tokens=8000)
    if model is None:
        return None
    summary = plan_pack.summary_text() if plan_pack is not None else ""
    agent = build_generator_agent(name="tpd_steps_gen",
                                  prompt=steps_prompt(scenarios, plan, summary, test_data),
                                  output_schema=StepsList, output_key="tpd_steps", model=model)
    data = await run_json_agent(agent, output_key="tpd_steps")
    if not data:
        log.warning("could not parse steps output; falling back to heuristic")
        return None
    return StepsList(**data).to_steps(test_data) or None


async def claude_test_data(plan: TestPlan, plan_pack, *, now: str = "",
                           model=None) -> list[TestData] | None:
    model = model or agent_model(max_tokens=6000)
    if model is None:
        return None
    agent = build_generator_agent(name="tpd_testdata_gen",
                                  prompt=testdata_prompt(plan, plan_pack.summary_text()),
                                  output_schema=TestDataList, output_key="tpd_test_data", model=model)
    data = await run_json_agent(agent, output_key="tpd_test_data")
    if not data:
        log.warning("could not parse test-data output; falling back to heuristic")
        return None
    return TestDataList(**data).to_test_data(plan, now) or None
