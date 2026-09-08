"""Generate the step-by-step test steps for a scenario."""

from __future__ import annotations

import os

from test_plan_definition.models import BOUNDARY, ERROR, NEGATIVE, TestPlan, TestScenario, TestStep

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
        low = m.lower()
        if "negative" not in low and "coverage" not in low and "happy" not in low:
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
    out = []
    for order, (kw, action, expected) in enumerate(template, start=1):
        action = action.replace("the test data", data)
        out.append(TestStep(
            id=f"{scenario.id}#s{order}", scenario_id=scenario.id, order=order, keyword=kw,
            action=action, expected=passed if expected == "PASS_METRIC" else expected,
            data_refs=scenario.data_refs,
        ))
    return out


async def generate_all_steps(
    scenarios: list[TestScenario], plan: TestPlan, plan_pack=None, test_data=None, *, now: str = "",
    detail: bool = False, model=None,
) -> list[TestStep]:
    """Detailed keyworded heuristic steps by default; opt into the batched StepsGen ``LlmAgent`` per
    ``detail``/``TPD_LLM_DETAIL`` (one LLM call per ``_STEP_BATCH`` chunk — kept off the I3 default)."""
    if detail or os.environ.get("TPD_LLM_DETAIL"):
        from test_plan_definition.llm.steps import claude_steps

        by_id: dict[str, list[TestStep]] = {}
        for i in range(0, len(scenarios), _STEP_BATCH):
            part = await claude_steps(scenarios[i:i + _STEP_BATCH], plan, plan_pack, test_data or [],
                                      now=now, model=model)
            if part:
                by_id.update(part)
        if by_id:
            return [st for sc in scenarios for st in (by_id.get(sc.id) or generate_steps(sc, plan))]
    return [st for sc in scenarios for st in generate_steps(sc, plan)]
