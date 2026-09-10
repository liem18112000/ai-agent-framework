"""P0 + P4 tests: prompt grounding and the assured generation loop (generate→judge→gate→reflect).

Everything is offline — the judge/generator are the injected ``FakeGeneratorModel`` (canned JSON,
call-counted), never the real Vertex network. The default (assured-off) path stays the I3 one call.
"""

from __future__ import annotations

from common.interrogate.pack import Pack
from common.memory import MemoryBank
from common.testplan import memory as store
from common.testplan.llm.prompts import (
    judge_scenarios_prompt,
    scenarios_prompt,
)
from common.testplan.models import CONFIRMED, TestPlan, TestScenario
from common.testplan.pack import PlanPack
from test_plan_definition.define import define
from test_plan_definition.implement import implement_plan
from test_plan_definition.implement.generate.llm import claude_judge_scenarios
from tests.tpd_fakes import FakeGeneratorModel, full_fake_model, judge_verdict


def _plan() -> TestPlan:
    return TestPlan(id="plan:run-x", context_id="run-x", methodology=["api"], status=CONFIRMED,
                    scope=["jira:LUZ-1"], metrics=["End-state verified"])


def _plan_pack() -> PlanPack:
    return PlanPack(pack=Pack(context_id="run-x", seed="LUZ-1"), understanding="X is done.")


def _scenario() -> TestScenario:
    return TestScenario(id="scenario:run-x:a", plan_id="plan:run-x", title="A", kind="happy",
                        source_refs=["jira:LUZ-1"])


async def _confirmed(bank):
    result = await define(bank, "run-6f2a", seed="LUZ-158390")
    assert result.plan.status == CONFIRMED
    return result.plan


# --- P0: prompt grounding --------------------------------------------------------------------

def test_scenarios_prompt_carries_gherkin_and_pack_grounding():
    text = scenarios_prompt(_plan(), "the pack", [])
    assert "Gherkin best practices" in text
    assert "Ground every scenario in the pack" in text
    assert "Do NOT invent requirements" in text
    # first pass (no reflections) carries no revision block
    assert "REVISION FEEDBACK" not in text


def test_scenarios_prompt_appends_revision_feedback_when_reflecting():
    text = scenarios_prompt(_plan(), "the pack", [], ["Add a boundary case for the limit"])
    assert "REVISION FEEDBACK" in text
    assert "Add a boundary case for the limit" in text


def test_judge_prompt_avoids_generator_router_markers():
    """The judge must not collide with the generator router substrings (its marker is QA CRITIC)."""
    text = judge_scenarios_prompt(_plan(), "the pack", [_scenario()])
    assert "QA CRITIC" in text
    for marker in ("TEST SCENARIOS", "TEST DATA", "STEP-BY-STEP"):
        assert marker not in text


# --- P4: the judge seam ----------------------------------------------------------------------

async def test_claude_judge_scenarios_parses_verdict():
    fake = FakeGeneratorModel(model="fake", judge_json=judge_verdict(0.82, reflections=["r1"]))
    verdict = await claude_judge_scenarios(_plan(), _plan_pack(), [_scenario()], model=fake)
    assert verdict is not None
    assert abs(verdict.score() - 0.82) < 1e-6
    assert verdict.reflections == ["r1"]
    assert fake.judge_calls == 1


async def test_claude_judge_scenarios_degrades_to_none_on_bad_output():
    fake = FakeGeneratorModel(model="fake", judge_json="not json at all")
    assert await claude_judge_scenarios(_plan(), _plan_pack(), [_scenario()], model=fake) is None


# --- P4: the assured loop --------------------------------------------------------------------

async def test_assured_accepts_on_first_round_when_score_clears_bar(pack_bucket, monkeypatch):
    monkeypatch.delenv("TPD_LLM_DETAIL", raising=False)
    bank = MemoryBank(pack_bucket)
    await _confirmed(bank)
    fake = full_fake_model()  # judge = 0.9 ≥ 0.7

    res = await implement_plan(bank, "run-6f2a", assured=True, model=fake)
    assert res.quality is not None
    assert res.quality.accepted and res.quality.rounds == 1
    assert abs(res.quality.final_score - 0.9) < 1e-6
    assert fake.calls == 2 and fake.judge_calls == 1  # 1 generate + 1 judge; data/steps heuristic
    assert {s.id for s in res.scenarios} == {"scenario:run-6f2a:a", "scenario:run-6f2a:b"}


async def test_assured_reflects_then_regenerates_until_accepted(pack_bucket, monkeypatch):
    monkeypatch.delenv("TPD_LLM_DETAIL", raising=False)
    bank = MemoryBank(pack_bucket)
    await _confirmed(bank)
    fake = full_fake_model()
    fake.judge_queue = [judge_verdict(0.4, reflections=["Add a boundary scenario for the max limit"]),
                        judge_verdict(0.85)]

    res = await implement_plan(bank, "run-6f2a", assured=True, model=fake)
    assert res.quality.accepted and res.quality.rounds == 2
    assert fake.judge_calls == 2 and fake.calls == 4  # 2 generate + 2 judge
    # the reflexion feedback threaded into the SECOND generation prompt
    assert any("REVISION FEEDBACK" in t and "Add a boundary scenario for the max limit" in t
               for t in fake.seen)


async def test_assured_below_bar_surfaces_for_human_review(pack_bucket, monkeypatch):
    monkeypatch.delenv("TPD_LLM_DETAIL", raising=False)
    monkeypatch.setenv("TPD_ASSURED_MAX_ITERS", "2")
    bank = MemoryBank(pack_bucket)
    await _confirmed(bank)
    fake = full_fake_model()
    fake.judge_json = judge_verdict(0.3)  # never clears the bar

    res = await implement_plan(bank, "run-6f2a", assured=True, model=fake)
    assert res.quality is not None and not res.quality.accepted
    assert res.quality.rounds == 2 and "human review" in res.quality.note
    assert res.scenarios  # still emits the best-effort best set (never empty)


async def test_assured_persists_and_resumes_rather_than_restarts(pack_bucket, monkeypatch):
    monkeypatch.delenv("TPD_LLM_DETAIL", raising=False)
    monkeypatch.setenv("TPD_ASSURED_MAX_ITERS", "2")
    bank = MemoryBank(pack_bucket)
    await _confirmed(bank)
    # simulate a handler killed after round 1 (not accepted), with a carried reflection
    store.write_assured_state(bank, "run-6f2a", {
        "iterations": [{"iter": 1, "score": 0.4, "accepted": False, "issues": []}],
        "reflections": ["Cover the negative path"], "accepted": False})
    fake = full_fake_model()  # judge 0.9 → accepts on the one remaining round

    res = await implement_plan(bank, "run-6f2a", assured=True, model=fake)
    assert res.quality.accepted and res.quality.rounds == 2  # resumed round 1 + one new round
    assert fake.judge_calls == 1  # only ONE new round ran — the completed round was not redone
    assert any("Cover the negative path" in t for t in fake.seen)  # carried reflection re-used
    assert store.read_assured_state(bank, "run-6f2a")["accepted"] is True


async def test_default_path_is_unchanged_when_assured_off(pack_bucket, monkeypatch):
    """I3 guard for the new branch: assured off → no judge, no quality, no state, one LLM call."""
    monkeypatch.delenv("TPD_LLM_DETAIL", raising=False)
    monkeypatch.delenv("TPD_ASSURED", raising=False)
    bank = MemoryBank(pack_bucket)
    await _confirmed(bank)
    fake = full_fake_model()

    res = await implement_plan(bank, "run-6f2a", model=fake)
    assert res.quality is None
    assert fake.calls == 1 and fake.judge_calls == 0
    assert store.read_assured_state(bank, "run-6f2a") == {}
