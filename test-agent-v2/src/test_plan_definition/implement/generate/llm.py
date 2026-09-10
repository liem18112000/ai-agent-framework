"""Claude-on-Vertex generator for the implement stage — scenarios, the I3 default LLM call. Returns
None (→ heuristic fallback) when unconfigured or the output fails schema. (The other generators are
inlined at their sole call sites: the P4 judge in ``assured.py``, steps in ``steps.py``, test-data in
``testdata.py``.)"""

from __future__ import annotations

from common.adk import agent_model
from common.testplan.llm.adk import build_generator_agent, run_json_agent
from common.testplan.llm.prompts import pack_block, scenarios_prompt
from common.testplan.llm.schemas import Scenarios
from common.testplan.models import TestData, TestPlan, TestScenario
from test_plan_definition.monitoring import get_logger

log = get_logger("llm.implement")


async def claude_scenarios(plan: TestPlan, plan_pack, test_data: list[TestData], *,
                           now: str = "", model=None,
                           reflections: list[str] | None = None) -> list[TestScenario] | None:
    model = model or agent_model(max_tokens=6000)
    if model is None:
        return None
    summary = plan_pack.summary_text()
    agent = build_generator_agent(
        name="tpd_scenario_gen", system=pack_block(summary),
        output_schema=Scenarios, output_key="tpd_scenarios", model=model)
    data = await run_json_agent(agent, output_key="tpd_scenarios",
                                user=scenarios_prompt(plan, summary, test_data, reflections,
                                                      include_context=False))
    if not data:
        log.warning("no scenarios from generator; falling back to heuristic")
        return None
    return Scenarios(**data).to_scenarios(plan, now) or None
