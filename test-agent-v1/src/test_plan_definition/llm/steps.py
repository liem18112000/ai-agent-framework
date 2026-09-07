"""Claude-on-Vertex generator for detailed step-by-step STEPS.

One bulk call produces Given/When/Then steps for every scenario at once (keyed by scenario id),
so a 30-scenario suite is one request, not thirty. Returns a {scenario_id: [TestStep]} map, or
None on a parse miss so the caller falls back to the heuristic per scenario. Mirrors llm/scenarios.py.
"""

from __future__ import annotations

from common.llm.parse import loads_array
from common.llm.vertex import complete
from test_plan_definition.llm.prompts import steps_prompt
from test_plan_definition.models import TestPlan, TestScenario, TestStep
from test_plan_definition.monitoring import get_logger

log = get_logger("llm.steps")


def claude_steps(
    scenarios: list[TestScenario], plan: TestPlan, plan_pack, test_data, *,
    project: str, location: str, model: str, now: str = "",
) -> dict[str, list[TestStep]] | None:
    summary = plan_pack.summary_text() if plan_pack is not None else ""
    raw = complete(
        steps_prompt(scenarios, plan, summary, test_data),
        # Called per batch (see generate_all_steps _STEP_BATCH), so this covers ~8 scenarios ×4 steps
        # of JSON. 8000 leaves ample headroom; the batching is what prevents the truncation fallback.
        project=project, location=location, model=model, max_tokens=8000,
    )
    items = loads_array(raw)  # [{scenario_id, steps:[{order, keyword, action, expected}]}]
    if not items:
        log.warning("could not parse steps output as JSON; falling back to heuristic")
        return None
    data_refs = [d.id for d in test_data]
    by_id: dict[str, list[TestStep]] = {}
    for it in items:
        sid = it.get("scenario_id")
        if not sid:
            continue
        steps = []
        for i, s in enumerate(it.get("steps") or [], start=1):
            order = s.get("order", i)
            steps.append(TestStep(
                id=f"{sid}#s{order}", scenario_id=sid, order=order,
                action=s.get("action", ""), expected=s.get("expected", ""),
                keyword=s.get("keyword", ""), data_refs=data_refs,
            ))
        if steps:
            by_id[sid] = steps
    return by_id or None
