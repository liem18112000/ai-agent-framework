"""Claude-on-Vertex generator for test scenarios from a confirmed plan."""

from __future__ import annotations

from common.llm.parse import loads_array
from common.llm.vertex import complete
from test_plan_definition.llm.prompts import scenarios_prompt
from test_plan_definition.models import HAPPY, TestData, TestPlan, TestScenario
from test_plan_definition.monitoring import get_logger

log = get_logger("llm.scenarios")

_FIELDS = ("id", "plan_id", "title", "kind", "methodology", "description", "rationale",
           "preconditions", "data_refs", "source_refs", "created_at")


def claude_scenarios(
    plan: TestPlan, plan_pack, test_data: list[TestData], *,
    project: str, location: str, model: str, now: str = "",
) -> list[TestScenario] | None:
    raw = complete(
        scenarios_prompt(plan, plan_pack.summary_text(), test_data),
        project=project, location=location, model=model, max_tokens=6000,
    )
    items = loads_array(raw)
    if not items:
        log.warning("could not parse scenarios output as JSON; falling back to heuristic")
        return None
    default_method = plan.methodology[0] if plan.methodology else "api"
    out = []
    for it in items:
        it.setdefault("plan_id", plan.id)
        it.setdefault("kind", HAPPY)
        it.setdefault("methodology", default_method)
        it["created_at"] = now
        out.append(TestScenario(**{k: it.get(k) for k in _FIELDS if k in it}))
    return out
