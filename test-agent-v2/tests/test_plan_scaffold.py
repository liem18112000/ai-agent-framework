"""M0 scaffold sanity: models round-trip, PlanPack, agent card, and the ASGI app build."""

from __future__ import annotations

from dataclasses import asdict

from common.testplan.models import ROUNDS, TestPlan, TestScenario
from common.testplan.pack import PlanPack


def test_rounds_are_the_define_set():
    assert ROUNDS == ("methodology", "scope", "metrics", "test-design")


def test_models_roundtrip():
    plan = TestPlan(id="plan:run-x", context_id="run-x", methodology=["api"], metrics=["end-state"])
    assert asdict(plan)["methodology"] == ["api"]
    sc = TestScenario(id="s1", plan_id=plan.id, title="happy path")
    assert sc.kind == "happy" and sc.methodology == "api"


def test_planpack_empty_when_no_grounding():
    from common.interrogate.pack import Pack

    pack = PlanPack(pack=Pack(context_id="run-x"), understanding="")
    assert pack.context_id == "run-x"
    assert pack.is_empty()


async def test_a2a_app_builds_and_serves_the_surface():
    from starlette.applications import Starlette

    from test_plan_definition.agent import build_root_agent
    from tests.conftest import adk_a2a_app

    app = adk_a2a_app(build_root_agent)
    assert isinstance(app, Starlette)
    async with app.router.lifespan_context(app):
        paths = {r.path for r in app.router.routes}
    assert "/" in paths and "/.well-known/agent-card.json" in paths
