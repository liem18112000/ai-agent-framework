"""M0 scaffold sanity: models round-trip, PlanPack, agent card, and the ASGI app build."""

from __future__ import annotations

from dataclasses import asdict

from test_plan_definition.agent import AGENT_CARD
from test_plan_definition.models import ROUNDS, TestPlan, TestScenario
from test_plan_definition.pack import PlanPack


def test_rounds_are_the_define_triplet():
    assert ROUNDS == ("methodology", "scope", "metrics")


def test_models_roundtrip():
    plan = TestPlan(id="plan:run-x", context_id="run-x", methodology=["api"], metrics=["end-state"])
    assert asdict(plan)["methodology"] == ["api"]
    sc = TestScenario(id="s1", plan_id=plan.id, title="happy path")
    assert sc.kind == "happy" and sc.methodology == "api"


def test_agent_card_advertises_define_and_implement():
    ids = {s.id for s in AGENT_CARD.skills}
    assert {"define-test-plan", "implement-test-plan"} <= ids
    assert AGENT_CARD.name == "test-plan-definition"


def test_planpack_empty_when_no_grounding():
    from common.interrogate.pack import Pack

    pack = PlanPack(pack=Pack(context_id="run-x"), understanding="")
    assert pack.context_id == "run-x"
    assert pack.is_empty()


def test_server_app_builds():
    from test_plan_definition.server import app

    paths = {r.path for r in app.router.routes}
    assert "/livez" in paths and "/readyz" in paths
    assert any(".well-known" in p for p in paths)
