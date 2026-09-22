"""Generate the step-by-step test steps for a scenario."""

from __future__ import annotations

import os

from common.adk import agent_model
from common.testplan.llm.adk import build_generator_agent, run_json_agent
from common.testplan.llm.prompts import pack_block, steps_prompt
from common.testplan.llm.schemas import StepsList
from common.testplan.models import BOUNDARY, ERROR, NEGATIVE, TestPlan, TestScenario, TestStep
from test_plan_definition.monitoring import get_logger

log = get_logger("llm.implement")

_STEP_BATCH = 8

_KIND_STEPS = {
    NEGATIVE: [
        ("Given", "invalid or unauthorized input is prepared", "the invalid request is ready"),
        ("When", "the API request is sent with that input", "the request is processed"),
        ("Then", "the request is rejected", "a 4xx status is returned"),
        ("And", "no side effects are persisted", "the end state is unchanged"),
    ],
    BOUNDARY: [
        ("Given", "input at the boundary (empty, single, or maximum size) is prepared",
         "the boundary request is ready"),
        ("When", "the API request is sent", "the request is processed at the limit"),
        ("Then", "the limit is handled without error", "the boundary is accepted"),
        ("And", "the resulting outcome is asserted", "PASS_METRIC"),
    ],
    ERROR: [
        ("Given", "a dependency/failure condition is arranged (backend down or malformed entry)",
         "the failure is injected"),
        ("When", "the API request is sent under that condition", "the request is processed"),
        ("Then", "the call fails gracefully", "a clear error with the correct status is returned"),
        ("And", "no partial or inconsistent state is persisted", "the end state is consistent"),
    ],
}
_HAPPY_STEPS = [
    ("Given", "an authenticated test account and valid mock data exist",
     "the preconditions are satisfied"),
    ("When", "a valid API request is sent with the test data", "the request is accepted"),
    ("Then", "the response status is 2xx", "the request succeeds"),
    ("And", "the resulting end state is asserted", "PASS_METRIC"),
]


def _pass_metric(plan: TestPlan) -> str:
    """The metric that states what 'passed' means — not the coverage-bar metric."""
    for m in plan.metrics:
        if not any(k in m.lower() for k in ("negative", "coverage", "happy")):
            return m
    return plan.metrics[0] if plan.metrics else "the expected end state holds"


def generate_steps(scenario: TestScenario, plan: TestPlan) -> list[TestStep]:
    passed = _pass_metric(plan)
    data = ", ".join(scenario.data_refs) if scenario.data_refs else "the test data"

    if scenario.methodology != "api":
        return [TestStep(id=f"{scenario.id}#s1", scenario_id=scenario.id, order=1, keyword="Given",
                         action=f"the {scenario.methodology} flow is exercised (step detail deferred — POC)",
                         expected=passed, data_refs=scenario.data_refs)]

    template = _KIND_STEPS.get(scenario.kind, _HAPPY_STEPS)
    return [
        TestStep(
            id=f"{scenario.id}#s{order}", scenario_id=scenario.id, order=order, keyword=kw,
            action=action.replace("the test data", data),
            expected=passed if expected == "PASS_METRIC" else expected, data_refs=scenario.data_refs)
        for order, (kw, action, expected) in enumerate(template, start=1)
    ]


async def generate_all_steps(
    scenarios: list[TestScenario], plan: TestPlan, plan_pack=None, test_data=None, *,
    detail: bool = False, model=None,
) -> list[TestStep]:
    """Detailed keyworded heuristic steps by default; opt into the batched StepsGen ``LlmAgent`` per
    ``detail``/``TPD_LLM_DETAIL`` (one LLM call per ``_STEP_BATCH`` chunk — kept off the I3 default).

    The generator run is inlined here (its sole caller): the stable context pack is the agent's cached
    system instruction (``pack_block``) and the per-batch TASK is the user turn (``steps_prompt``, so
    the pack isn't duplicated), matching the other implement generators."""
    if detail or os.environ.get("TPD_LLM_DETAIL"):
        model = model or agent_model()  # inherit the ceiling — a cap truncates the steps mid-JSON
        if model is not None:
            td = test_data or []
            summary = plan_pack.summary_text() if plan_pack is not None else ""
            by_id: dict[str, list[TestStep]] = {}
            for i in range(0, len(scenarios), _STEP_BATCH):
                agent = build_generator_agent(name="tpd_steps_gen", system=pack_block(summary),
                                              output_schema=StepsList, output_key="tpd_steps", model=model)
                data = await run_json_agent(agent, output_key="tpd_steps", user=steps_prompt(
                    scenarios[i:i + _STEP_BATCH], plan, summary, td, include_context=False))
                if not data:
                    log.warning("could not parse steps output; falling back to heuristic")
                    continue
                if part := StepsList(**data).to_steps(td):
                    by_id.update(part)
            if by_id:
                return [st for sc in scenarios for st in (by_id.get(sc.id) or generate_steps(sc, plan))]
    return [st for sc in scenarios for st in generate_steps(sc, plan)]
