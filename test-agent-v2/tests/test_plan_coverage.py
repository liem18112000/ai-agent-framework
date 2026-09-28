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


def test_orphan_scenarios_are_reported_not_silently_dropped():
    """R2: a scenario citing nothing resolvable serves NO stated intent. It is absent from `covered`
    by construction, so before R2 nothing anywhere reported it — the matrix only measured recall."""
    plan = _plan(test_kinds=["happy"])
    pack = _pack(Note(id="jira:A", type="note", title="Login"))
    scenarios = [_sc("s1", "happy", "jira:A"),            # serves a real unit
                 _sc("s2", "happy", "jira:GONE"),         # dangling ref
                 TestScenario(id="s3", plan_id="plan:run-x", title="untraced", kind="happy")]  # cites none
    m = build_coverage_matrix(None, "run-x", plan=plan, pack=pack, scenarios=scenarios)

    assert m.scenarios_total == 3
    assert {s["id"] for s in m.orphan_scenarios} == {"s2", "s3"}
    assert m.drift_count == 2
    # …and the reader actually sees it
    md = render_coverage_md(m)
    assert "Drift (2 of 3 scenarios)" in md and "cites no requirement unit" in md


def test_out_of_scope_hits_flag_scenarios_the_plan_ruled_out():
    """R2: the plan says QR code fallback is out of scope; a scenario testing it is drift."""
    plan = _plan(test_kinds=["happy"], out_of_scope=["QR code fallback removal"])
    pack = _pack(Note(id="jira:A", type="note", title="Login"))
    scenarios = [_sc("s1", "happy", "jira:A", title="User logs in with valid credentials"),
                 _sc("s2", "happy", "jira:A", title="QR code fallback removal for company accounts")]
    m = build_coverage_matrix(None, "run-x", plan=plan, pack=pack, scenarios=scenarios)

    assert [s["id"] for s in m.out_of_scope_hits] == ["s2"]
    assert m.out_of_scope_hits[0]["matched"] == "QR code fallback removal"
    assert m.orphan_scenarios == []          # both cite a real unit — this is the OTHER drift axis
    assert "out-of-scope" in render_coverage_md(m)


def test_out_of_scope_hits_match_node_ids_the_production_shape():
    """R2, the shape that actually reaches coverage in production: the assured loop overwrites
    plan.out_of_scope with `grounded_ids - in_scope_ids` from the scope classifier and persists it,
    so the field holds pack NODE IDS, not prose. Matched exactly against source_refs — a prose-only
    token matcher would have been near-dead here (it would need the scenario text to name the id)."""
    plan = _plan(test_kinds=["happy"], out_of_scope=["jira:B"])   # classifier ruled B out
    pack = _pack(Note(id="jira:A", type="note", title="Login"),
                 Note(id="jira:B", type="note", title="Legacy export"))
    scenarios = [_sc("s1", "happy", "jira:A", title="valid login"),
                 _sc("s2", "happy", "jira:B", title="exports the legacy file")]
    m = build_coverage_matrix(None, "run-x", plan=plan, pack=pack, scenarios=scenarios)

    assert [s["id"] for s in m.out_of_scope_hits] == ["s2"]
    assert m.out_of_scope_hits[0]["matched"] == "jira:B"
    assert m.orphan_scenarios == []      # s2 cites a REAL unit — it is out-of-scope, not orphaned


def test_drift_findings_carry_a_cause_disposition():
    """R7: every drift finding is disposed by CAUSE, openrig's one word per miss. An empty pack had
    nothing to cite (CONTEXT-GAP → fix gather); a populated one means the generator had the units and
    still cited none (JUDGMENT-GAP → fix the prompt). The RATE is the calibration signal."""
    from common.testplan.coverage import CONTEXT_GAP, JUDGMENT_GAP, as_dict, coverage_summary

    # empty pack — nothing existed to cite
    starved = build_coverage_matrix(None, "run-x", plan=_plan(test_kinds=["happy"]), pack=_pack(),
                                    scenarios=[_sc("s1", "happy", "jira:A")])
    assert [s["cause"] for s in starved.orphan_scenarios] == [CONTEXT_GAP]
    assert starved.drift_causes == {CONTEXT_GAP: 1}

    # populated pack — the generator had a unit and cited nothing resolvable
    rich = build_coverage_matrix(
        None, "run-x", plan=_plan(test_kinds=["happy"], out_of_scope=["jira:B"]),
        pack=_pack(Note(id="jira:A", type="note", title="Login"),
                   Note(id="jira:B", type="note", title="Legacy")),
        scenarios=[_sc("s1", "happy", "jira:GONE"),      # orphan, units existed
                   _sc("s2", "happy", "jira:B")])        # reached past the stated boundary
    assert [s["cause"] for s in rich.orphan_scenarios] == [JUDGMENT_GAP]
    assert [s["cause"] for s in rich.out_of_scope_hits] == [JUDGMENT_GAP]
    assert rich.drift_causes == {JUDGMENT_GAP: 2}

    assert "2 JUDGMENT-GAP" in coverage_summary(rich)
    assert "Disposition:" in render_coverage_md(rich)
    assert as_dict(rich)["drift_causes"] == {JUDGMENT_GAP: 2}   # the rate survives persistence


def test_a_clean_suite_reports_no_drift():
    """The quiet case must stay quiet — no Drift section, no drift clause in the summary."""
    from common.testplan.coverage import as_dict, coverage_summary

    plan = _plan(test_kinds=["happy"], out_of_scope=["QR code fallback"])
    m = build_coverage_matrix(None, "run-x", plan=plan,
                              pack=_pack(Note(id="jira:A", type="note", title="Login")),
                              scenarios=[_sc("s1", "happy", "jira:A", title="valid login")])
    assert m.drift_count == 0 and m.orphan_scenarios == [] and m.out_of_scope_hits == []
    assert "Drift" not in render_coverage_md(m)
    assert "DRIFT" not in coverage_summary(m)
    assert as_dict(m)["drift_count"] == 0     # persisted JSON carries the property


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
