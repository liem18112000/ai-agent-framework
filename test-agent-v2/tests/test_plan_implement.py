"""M3 tests: implement — generate test data / scenarios / steps from a confirmed plan."""

from __future__ import annotations

from common.memory import MemoryBank
from common.testplan import memory as store
from common.testplan.models import BOUNDARY, CONFIRMED, ERROR, HAPPY, NEGATIVE, TEST_SCENARIO
from test_plan_definition.define import define
from test_plan_definition.implement import implement_plan
from tests.tpd_fakes import full_fake_model


async def _confirmed(bank):
    result = await define(bank, "run-6f2a", seed="LUZ-158390")
    assert result.plan.status == CONFIRMED
    return result.plan


async def test_implement_generates_and_persists_artifacts(pack_bucket):
    bank = MemoryBank(pack_bucket)
    await _confirmed(bank)

    res = await implement_plan(bank, "run-6f2a")
    assert res.plan and res.scenarios and res.test_data and res.steps
    kinds = {s.kind for s in res.scenarios}
    assert {HAPPY, NEGATIVE, BOUNDARY, ERROR} <= kinds
    assert all(s.source_refs for s in res.scenarios)
    td_kinds = {d.kind for d in res.test_data}
    assert "test-account" in td_kinds and "mock-data" in td_kinds
    assert all(s.description and s.rationale for s in res.scenarios)
    covered = {st.scenario_id for st in res.steps}
    assert covered == {s.id for s in res.scenarios}

    assert store.read_scenarios(bank, "run-6f2a")
    assert store.read_steps(bank, "run-6f2a")
    assert store.read_test_data(bank, "run-6f2a")
    assert "Test Scenarios" in (store.read_scenarios_md(bank, "run-6f2a") or "")


async def test_implement_adds_provenance_nodes_to_the_shared_index(pack_bucket):
    bank = MemoryBank(pack_bucket)
    await _confirmed(bank)
    await implement_plan(bank, "run-6f2a")

    graph, _ = bank.load_index()
    node_types = {n["type"] for n in graph.nodes.values()}
    assert "test-plan" in node_types and TEST_SCENARIO in node_types
    sc_edges = [e for e in graph.edges.values() if e["type"] == TEST_SCENARIO]
    assert sc_edges and all(e["target"] for e in sc_edges)


async def test_implement_refuses_when_no_confirmed_plan(pack_bucket):
    bank = MemoryBank(pack_bucket)
    res = await implement_plan(bank, "run-6f2a")
    assert not res.scenarios
    assert "run define first" in res.message


async def test_api_steps_are_request_then_assert(pack_bucket):
    bank = MemoryBank(pack_bucket)
    await _confirmed(bank)
    res = await implement_plan(bank, "run-6f2a")
    happy = next(s for s in res.scenarios if s.kind == HAPPY)
    steps = sorted((st for st in res.steps if st.scenario_id == happy.id), key=lambda s: s.order)
    assert len(steps) >= 3 and steps[0].order == 1
    assert steps[0].keyword == "Given" and any(s.keyword == "When" for s in steps)
    assert "request" in " ".join(s.action.lower() for s in steps) and steps[-1].expected


# --- call-count gate (assured always-on: default = 2 = generate + judge; detail = 4) ------------

async def test_implement_default_makes_two_llm_calls_generate_plus_judge(pack_bucket, monkeypatch):
    """The always-on assured loop is the scenario path: a default implement makes TWO LLM calls —
    scenario-generate + judge (test-data + steps stay heuristic). This replaced the old I3 single-call
    default; the loop's serial-Vertex cost is bounded by TPD_ASSURED_MAX_ITERS (keep =1 in a
    latency-sensitive deploy to stay clear of the Cloud-Run request timeout)."""
    monkeypatch.delenv("TPD_LLM_DETAIL", raising=False)
    bank = MemoryBank(pack_bucket)
    await _confirmed(bank)
    fake = full_fake_model()

    res = await implement_plan(bank, "run-6f2a", model=fake)
    assert fake.calls == 2 and fake.judge_calls == 1  # 1 generate + 1 judge; test-data/steps heuristic
    assert {s.id for s in res.scenarios} == {"scenario:run-6f2a:a", "scenario:run-6f2a:b"}
    assert res.quality is not None and res.quality.accepted  # judge 0.9 ≥ 0.7 → accepts round 1


async def test_implement_detail_makes_four_llm_calls(pack_bucket, monkeypatch):
    """detail on → test-data + (scenario-generate + judge) + one steps-batch = 4 LLM calls."""
    monkeypatch.delenv("TPD_LLM_DETAIL", raising=False)
    bank = MemoryBank(pack_bucket)
    await _confirmed(bank)
    fake = full_fake_model()

    await implement_plan(bank, "run-6f2a", detail=True, model=fake)
    assert fake.calls == 4, f"detail implement must make 4 LLM calls, made {fake.calls}"


async def test_implement_falls_back_to_heuristic_on_invalid_llm_output(pack_bucket, monkeypatch):
    """Invalid model output degrades to the heuristic scenarios — never raises (best-effort)."""
    monkeypatch.delenv("TPD_LLM_DETAIL", raising=False)
    bank = MemoryBank(pack_bucket)
    await _confirmed(bank)
    fake = full_fake_model()
    fake.scenarios_json = "not valid json at all"

    res = await implement_plan(bank, "run-6f2a", model=fake)
    assert fake.calls == 2  # generate (invalid → heuristic fallback) + judge on the heuristic scenarios
    # heuristic scenarios carry the '— happy path' style titles and the full kind matrix
    kinds = {s.kind for s in res.scenarios}
    assert {HAPPY, NEGATIVE, BOUNDARY, ERROR} <= kinds
    assert any("happy path" in s.title for s in res.scenarios)
