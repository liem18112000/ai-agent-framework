"""Claude-on-Vertex generators for the implement stage — scenarios (the I3 default call), steps,
test-data. Each returns None (→ heuristic fallback) when unconfigured or the output fails schema."""

from __future__ import annotations

from common.adk import agent_model
from common.testplan.llm.adk import build_generator_agent, run_json_agent
from common.testplan.llm.prompts import (
    judge_scenarios_prompt,
    scenarios_prompt,
    steps_prompt,
    testdata_prompt,
)
from common.testplan.llm.schemas import JudgeVerdict, Scenarios, StepsList, TestDataList
from common.testplan.models import TestData, TestPlan, TestScenario, TestStep
from test_plan_definition.monitoring import get_logger

log = get_logger("llm.implement")


async def claude_scenarios(plan: TestPlan, plan_pack, test_data: list[TestData], *,
                           now: str = "", model=None,
                           reflections: list[str] | None = None) -> list[TestScenario] | None:
    model = model or agent_model(max_tokens=6000)
    if model is None:
        return None
    agent = build_generator_agent(
        name="tpd_scenario_gen",
        prompt=scenarios_prompt(plan, plan_pack.summary_text(), test_data, reflections),
        output_schema=Scenarios, output_key="tpd_scenarios", model=model)
    data = await run_json_agent(agent, output_key="tpd_scenarios")
    if not data:
        log.warning("no scenarios from generator; falling back to heuristic")
        return None
    return Scenarios(**data).to_scenarios(plan, now) or None


async def claude_judge_scenarios(plan: TestPlan, plan_pack, scenarios: list[TestScenario], *,
                                 model=None) -> JudgeVerdict | None:
    """The P4 LLM-as-judge (§3.4). Returns a validated ``JudgeVerdict`` or ``None`` when unconfigured
    / the output fails schema — the caller treats ``None`` as 'unscored, keep as-is' (never raises).
    Small ``max_tokens``: the verdict is short, keeping the per-iteration judge call cheap."""
    model = model or agent_model(max_tokens=1500)
    if model is None:
        return None
    agent = build_generator_agent(
        name="tpd_scenario_judge",
        prompt=judge_scenarios_prompt(plan, plan_pack.summary_text(), scenarios),
        output_schema=JudgeVerdict, output_key="tpd_verdict", model=model)
    data = await run_json_agent(agent, output_key="tpd_verdict")
    if not data:
        log.warning("no verdict from judge; scenarios kept unscored")
        return None
    return JudgeVerdict(**data)


async def claude_steps(scenarios: list[TestScenario], plan: TestPlan, plan_pack, test_data, *,
                       model=None) -> dict[str, list[TestStep]] | None:
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
