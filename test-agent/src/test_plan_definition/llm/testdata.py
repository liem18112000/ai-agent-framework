"""Claude-on-Vertex generator for TEST DATA from a confirmed plan.

Build the prompt, call Vertex, parse the JSON reply into `TestData`. Returns None on a parse
miss so the caller falls back to the heuristic. Mirrors llm/scenarios.py.
"""

from __future__ import annotations

from common.llm.parse import loads_array
from common.llm.vertex import complete
from test_plan_definition.llm.prompts import testdata_prompt
from test_plan_definition.models import TestData, TestPlan
from test_plan_definition.monitoring import get_logger

log = get_logger("llm.testdata")

_FIELDS = ("id", "kind", "plan_id", "spec", "source_refs", "created_at")


def claude_test_data(
    plan: TestPlan, plan_pack, *, project: str, location: str, model: str, now: str = "",
) -> list[TestData] | None:
    raw = complete(
        testdata_prompt(plan, plan_pack.summary_text()),
        # account + up to 8 mock records + a fixture is more than 2000 tokens of JSON; too small a
        # budget truncates the array so loads_array() fails and we silently fall back to heuristics.
        project=project, location=location, model=model, max_tokens=6000,
    )
    items = loads_array(raw)
    if not items:
        log.warning("could not parse test-data output as JSON; falling back to heuristic")
        return None
    out = []
    for it in items:
        it.setdefault("plan_id", plan.id)
        it["created_at"] = now
        if it.get("id") and it.get("kind"):
            out.append(TestData(**{k: it.get(k) for k in _FIELDS if k in it}))
    return out or None
