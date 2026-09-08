"""StepsGen — the detail-gated implement ``LlmAgent`` for step-by-step STEPS (batched upstream)."""

from __future__ import annotations

from common.adk import agent_model
from test_plan_definition.llm.adk import build_generator_agent, run_json_agent
from test_plan_definition.llm.prompts import steps_prompt
from test_plan_definition.llm.schemas import StepsList
from test_plan_definition.models import TestPlan, TestScenario, TestStep
from test_plan_definition.monitoring import get_logger

log = get_logger("llm.steps")

_MAX_TOKENS = 8000


async def claude_steps(
    scenarios: list[TestScenario], plan: TestPlan, plan_pack, test_data, *, now: str = "", model=None,
) -> dict[str, list[TestStep]] | None:
    """Structured steps for one scenario batch via the ``LlmAgent`` (batching is done by the caller);
    ``None`` (→ heuristic) when unconfigured or the model output fails schema validation."""
    model = model or agent_model(max_tokens=_MAX_TOKENS)
    if model is None:
        return None
    summary = plan_pack.summary_text() if plan_pack is not None else ""
    agent = build_generator_agent(
        name="tpd_steps_gen",
        prompt=steps_prompt(scenarios, plan, summary, test_data),
        output_schema=StepsList, output_key="tpd_steps", model=model)
    data = await run_json_agent(agent, output_key="tpd_steps")
    if not data:
        log.warning("could not parse steps output; falling back to heuristic")
        return None
    return StepsList(**data).to_steps(test_data) or None
