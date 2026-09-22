"""Q5 tests: the codegraph coverage matrix — requirement×kind traceability + gaps, codegraph code
units (endpoints/hubs) reached, persistence, and the implement integration."""

from __future__ import annotations

from common.codegraph.store import INDEX
from common.interrogate.pack import Pack
from common.memory import MemoryBank
from common.models import CODEGRAPH, Note
from common.testplan import memory as store
from common.testplan.coverage import build_coverage_matrix, render_coverage_md
from common.testplan.models import CONFIRMED, TestPlan, TestScenario
from test_plan_definition.define import define
from test_plan_definition.implement import implement_plan


def _plan(**kw) -> TestPlan:
    return TestPlan(id="plan:run-x", context_id="run-x", methodology=["api"], status=CONFIRMED, **kw)


def _pack(*notes: Note) -> Pack:
    p = Pack(context_id="run-x", seed="s")
    p.notes = list(notes)
    return p


def _sc(sid: str, kind: str, ref: str, title: str = "") -> TestScenario:
    return TestScenario(id=sid, plan_id="plan:run-x", title=title or sid, kind=kind, source_refs=[ref])


def test_requirement_kind_coverage_traceability_and_gaps():
    # test_kinds is ADDITIVE on the base four (effective_kinds), so the denominator is 2 units × 4
    # kinds = 8 cells — the same kind set generation covers, so coverage can't under/over-count.
    plan = _plan(test_kinds=["happy", "negative"])
    pack = _pack(Note(id="jira:A", type="note", title="Login"),
                 Note(id="jira:B", type="note", title="Checkout"))
    scenarios = [_sc("s1", "happy", "jira:A"), _sc("s2", "negative", "jira:A"),
                 _sc("s3", "happy", "jira:B")]
    m = build_coverage_matrix(None, "run-x", plan=plan, pack=pack, scenarios=scenarios)

    assert m.requirement_cells == 8 and m.requirement_cells_covered == 3  # A:{h,n}, B:{h} of {h,n,b,e}
    assert m.requirement_pct == 37.5
    assert m.covered["jira:A"] == ["happy", "negative"]
    # B covered only happy → missing the other three kinds
    gap = next(g for g in m.gaps if g["id"] == "jira:B")
    assert gap["missing"] == ["negative", "boundary", "error"]
    assert not m.has_codegraph  # no codegraph note in the pack


def test_no_codegraph_degrades_to_requirement_only():
    m = build_coverage_matrix(None, "run-x", plan=_plan(test_kinds=["happy"]),
                              pack=_pack(Note(id="jira:A", type="note", title="A")),
                              scenarios=[_sc("s1", "happy", "jira:A")])
    assert m.code_units == 0 and not m.has_codegraph
    assert "no codegraph" in render_coverage_md(m)


def test_codegraph_code_units_reached_and_gap():
    from tests.conftest import FakeBucket

    bank = MemoryBank(FakeBucket())
    bank.put_json(INDEX, [{"repo": "myrepo",
                           "endpoints": ["src/rest/OrderResource.java"],
                           "god_nodes": [{"name": "OrderService", "edges": 40}]}])
    pack = _pack(Note(id="jira:A", type="note", title="Order flow"),
                 Note(id="codegraph:ws/myrepo", type=CODEGRAPH, title="ws/myrepo"))
    # a scenario names the endpoint (reached); the OrderService hub is never named (gap)
    scenarios = [_sc("s1", "happy", "jira:A", title="Create order via OrderResource")]
    m = build_coverage_matrix(bank, "run-x", plan=_plan(test_kinds=["happy"]), pack=pack,
                              scenarios=scenarios)

    assert m.has_codegraph and m.code_units == 2  # 1 endpoint + 1 hub
    assert m.code_units_reached == 1
    assert any(u.id == "endpoint:myrepo:OrderResource.java" for u in m.units)
    assert "endpoint:myrepo:OrderResource.java" in m.reached_code
    assert any(g["id"] == "hub:myrepo:OrderService" for g in m.gaps)


async def test_implement_builds_and_persists_coverage(pack_bucket):
    bank = MemoryBank(pack_bucket)
    result = await define(bank, "run-6f2a", seed="LUZ-158390")
    assert result.plan.status == CONFIRMED

    res = await implement_plan(bank, "run-6f2a")
    assert res.coverage_summary and "AC×kind cells" in res.coverage_summary
    md = store.read_coverage_md(bank, "run-6f2a")
    assert md and "Coverage matrix" in md and "Traceability" in md
    assert store.read_coverage(bank, "run-6f2a").get("kinds")
