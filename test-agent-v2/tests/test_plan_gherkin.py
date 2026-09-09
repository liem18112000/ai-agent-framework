"""M5 tests: the BDD/Gherkin export of generated scenarios/steps."""

from __future__ import annotations

from common.memory import MemoryBank
from common.testplan import memory as store
from test_plan_definition.define import define
from test_plan_definition.implement import implement_plan
from test_plan_definition.implement.gherkin import export_features, render_feature


async def _implemented(bank):
    await define(bank, "run-6f2a", seed="LUZ-158390")
    return await implement_plan(bank, "run-6f2a")


async def test_implement_auto_exports_a_feature(pack_bucket):
    bank = MemoryBank(pack_bucket)
    res = await _implemented(bank)
    assert res.feature and res.feature.startswith("Feature:")
    saved = store.read_feature(bank, "run-6f2a", "run-6f2a")
    assert saved == res.feature


async def test_feature_has_tagged_scenarios_and_when_then(pack_bucket):
    bank = MemoryBank(pack_bucket)
    await _implemented(bank)
    feature = store.read_feature(bank, "run-6f2a", "run-6f2a")
    assert "@happy" in feature and "@negative" in feature
    assert "Scenario:" in feature
    assert "Given " in feature and "When " in feature and "Then " in feature


def test_render_feature_groups_steps_under_their_scenario():
    from common.testplan.models import HAPPY, TestScenario, TestStep

    scenarios = [TestScenario(id="s1", plan_id="p", title="Do X — happy path", kind=HAPPY,
                              data_refs=["td1"], source_refs=["n1"])]
    steps = [
        TestStep(id="s1#s2", scenario_id="s1", order=2, action="assert outcome", expected="ok"),
        TestStep(id="s1#s1", scenario_id="s1", order=1, action="send request", expected="2xx"),
    ]
    out = render_feature("Do X", scenarios, steps)
    assert out.index("send request") < out.index("assert outcome")
    assert "Feature: Do X" in out and "@happy" in out


async def test_export_none_when_no_scenarios(fake_bucket):
    bank = MemoryBank(fake_bucket)
    assert export_features(bank, "run-none") is None
