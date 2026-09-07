"""M3 tests: implement — generate test data / scenarios / steps from a confirmed plan.

First runs the define loop headlessly (accept_recommendation) to get a CONFIRMED plan, then
implements it. Everything is deterministic (heuristic generators, no LLM).
"""

from __future__ import annotations

from common.memory import MemoryBank
from test_plan_definition import memory as store
from test_plan_definition.define import define
from test_plan_definition.implement import implement_plan
from test_plan_definition.models import BOUNDARY, CONFIRMED, ERROR, HAPPY, NEGATIVE, TEST_SCENARIO


async def _confirmed(bank):
    result = await define(bank, "run-6f2a", seed="LUZ-158390")
    assert result.plan.status == CONFIRMED
    return result.plan


async def test_implement_generates_and_persists_artifacts(pack_bucket):
    bank = MemoryBank(pack_bucket)
    await _confirmed(bank)

    res = implement_plan(bank, "run-6f2a")
    assert res.plan and res.scenarios and res.test_data and res.steps
    # the agent generates the full coverage matrix per behaviour (happy + negative + boundary + error)
    kinds = {s.kind for s in res.scenarios}
    assert {HAPPY, NEGATIVE, BOUNDARY, ERROR} <= kinds
    # every scenario traces back to a grounded note (provenance)
    assert all(s.source_refs for s in res.scenarios)
    # richer test data (account + mock records) and case-by-case scenario detail
    td_kinds = {d.kind for d in res.test_data}
    assert "test-account" in td_kinds and "mock-data" in td_kinds
    assert all(s.description and s.rationale for s in res.scenarios)
    # every scenario has steps
    covered = {st.scenario_id for st in res.steps}
    assert covered == {s.id for s in res.scenarios}

    # persisted to the test-plan namespace
    assert store.read_scenarios(bank, "run-6f2a")
    assert store.read_steps(bank, "run-6f2a")
    assert store.read_test_data(bank, "run-6f2a")
    assert "Test Scenarios" in (store.read_scenarios_md(bank, "run-6f2a") or "")


async def test_implement_adds_provenance_nodes_to_the_shared_index(pack_bucket):
    bank = MemoryBank(pack_bucket)
    await _confirmed(bank)
    implement_plan(bank, "run-6f2a")

    graph, _ = bank.load_index()
    node_types = {n["type"] for n in graph.nodes.values()}
    assert "test-plan" in node_types and TEST_SCENARIO in node_types
    # a scenario node has an edge to the note/insight it covers
    sc_edges = [e for e in graph.edges.values() if e["type"] == TEST_SCENARIO]
    assert sc_edges and all(e["target"] for e in sc_edges)


async def test_implement_refuses_when_no_confirmed_plan(pack_bucket):
    bank = MemoryBank(pack_bucket)  # gathered/refined, but define never run
    res = implement_plan(bank, "run-6f2a")
    assert not res.scenarios
    assert "run define first" in res.message


def test_api_steps_are_request_then_assert(pack_bucket):
    import asyncio

    bank = MemoryBank(pack_bucket)
    asyncio.run(_confirmed(bank))
    res = implement_plan(bank, "run-6f2a")
    happy = next(s for s in res.scenarios if s.kind == HAPPY)
    steps = sorted((st for st in res.steps if st.scenario_id == happy.id), key=lambda s: s.order)
    # detailed step-by-step: arrange -> act (a request) -> assert, with BDD keywords
    assert len(steps) >= 3 and steps[0].order == 1
    assert steps[0].keyword == "Given" and any(s.keyword == "When" for s in steps)
    assert "request" in " ".join(s.action.lower() for s in steps) and steps[-1].expected
