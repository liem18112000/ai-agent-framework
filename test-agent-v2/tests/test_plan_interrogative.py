"""Q1/Q2/Q3-Q4 tests: the test-design define round, the open+uncapped kind taxonomy, and the
interrogative-implement ImplementSession."""

from __future__ import annotations

from common.interrogate.loop import accept_recommendation
from common.interrogate.pack import Pack
from common.interrogate.round.case_design import kinds_from_answer
from common.interrogate.round.test_design import recommend_methods
from common.memory import MemoryBank
from common.models import Note
from common.testplan import memory as store
from common.testplan.models import CONFIRMED, ROUNDS, TestData, TestPlan, effective_kinds
from common.testplan.pack import PlanPack
from test_plan_definition.define import define
from test_plan_definition.implement.generate.scenarios import heuristic_scenarios
from test_plan_definition.implement.interrogate.session import ImplementSession


def _plan(**kw) -> TestPlan:
    return TestPlan(id="plan:run-x", context_id="run-x", methodology=["api"],
                    scope=["jira:LUZ-1"], metrics=["End-state verified"], **kw)


def _pack_with(*titles: str) -> PlanPack:
    notes = [Note(id=f"jira:N{i}", type="note", title=t) for i, t in enumerate(titles)]
    pack = Pack(context_id="run-x", seed="LUZ-1")
    pack.notes = notes
    return PlanPack(pack=pack, understanding="")


# --- Q1: the test-design 4th define round + method suggestion ---------------------------------

def test_test_design_is_the_4th_define_round():
    assert ROUNDS == ("methodology", "scope", "metrics", "test-design")


def test_recommend_methods_reads_pack_signals():
    assert recommend_methods(_pack_with("dunning status lifecycle").pack)[0] \
        == "Equivalence Partitioning + Boundary Value Analysis"
    assert "State-transition testing" in recommend_methods(_pack_with("dunning status lifecycle").pack)
    assert "Decision table / cause-effect" in recommend_methods(_pack_with("eligibility rule matrix").pack)
    # a featureless pack still gets the EP+BVA base
    assert recommend_methods(_pack_with("a plain note").pack) == [
        "Equivalence Partitioning + Boundary Value Analysis"]


async def test_define_populates_test_design_in_the_plan(pack_bucket):
    bank = MemoryBank(pack_bucket)
    result = await define(bank, "run-6f2a", seed="LUZ-158390")
    assert result.plan.status == CONFIRMED
    assert result.plan.test_design, "the test-design round must land a method on the plan"
    assert "Test-design method" in (store.read_plan_brief(bank, "run-6f2a") or "")


# --- Q2: open, uncapped kind taxonomy ---------------------------------------------------------

def test_open_kind_taxonomy_flows_into_scenarios():
    plan = _plan(test_kinds=["security", "performance"])
    pack = _pack_with("Login", "Checkout")
    scs = heuristic_scenarios(plan, pack, [TestData(id="td", kind="mock-data")])
    kinds = {s.kind for s in scs}
    assert {"security", "performance"} <= kinds  # user-added kinds flow through
    assert {"happy", "negative", "boundary", "error"} <= kinds  # …ADDED to the base four, never replacing them
    assert any("security" in s.title for s in scs)


def test_no_note_cap_enumerates_every_behaviour():
    plan = _plan(test_kinds=["happy"])
    pack = _pack_with(*[f"behaviour {i}" for i in range(12)])  # > the old _MAX_NOTES=8 cap
    scs = heuristic_scenarios(plan, pack, [])
    assert len({s.source_refs[0] for s in scs}) == 12  # all 12 covered, not capped at 8


# --- Q3/Q4: the interrogative-implement session -----------------------------------------------

def test_kinds_from_answer_parses_open_kinds():
    assert kinds_from_answer("happy, negative, boundary, error") == \
        ["happy", "negative", "boundary", "error"]
    assert "security" in kinds_from_answer("+ security")
    assert kinds_from_answer("+ security")[:4] == ["happy", "negative", "boundary", "error"]
    assert kinds_from_answer("gibberish") == ["happy", "negative", "boundary", "error"]
    assert "negative" not in kinds_from_answer("happy, boundary — no negative cases")  # negation dropped


async def _confirm(bank):
    result = await define(bank, "run-6f2a", seed="LUZ-158390")
    assert result.plan.status == CONFIRMED


async def test_implement_session_updates_plan_test_kinds(pack_bucket):
    bank = MemoryBank(pack_bucket)
    await _confirm(bank)

    session = ImplementSession(bank, "run-6f2a", seed="run-6f2a")
    assert not session.is_empty()
    rounds_seen = []
    while (open_qs := session.next_questions()) is not None:
        rounds_seen.append(open_qs[0].round)
        if open_qs[0].round == "case-design":  # the user ADDS a kind the pack couldn't infer
            await session.submit(f"{open_qs[0].id}: + security")
        else:
            await session.submit(accept_recommendation(open_qs))
    brief = session.finalize()

    assert rounds_seen == ["case-design", "data-design", "step-oracle"]
    # the user-added 'security' kind flowed through — the taxonomy is open, not the fixed four
    assert "security" in brief.kinds and "happy" in brief.kinds
    assert store.read_plan(bank, "run-6f2a").test_kinds == brief.kinds  # persisted onto the plan
    assert store.read_implement_state(bank, "run-6f2a").get("done") is True
    assert store.read_implement_decisions(bank, "run-6f2a")
    assert "Implement design brief" in (store.read_implement_brief(bank, "run-6f2a") or "")


# --- regression: a mangled/collapsed test_kinds must never drop the base four ------------------
# The LUZ-158230 failure: the implement guidance fold-in collapsed test_kinds to ["performance"]
# (empty test_kinds + a steer mentioning "performance"), and `test_kinds or defaults` REPLACED the
# four, so the whole suite was 41 all-"performance" stubs (0 happy / 0 negative). `effective_kinds`
# makes the taxonomy ADDITIVE, so the base four survive any single-kind mangling.

def test_effective_kinds_unions_defaults_never_replaces():
    assert effective_kinds(_plan(test_kinds=["performance"])) == \
        ["happy", "negative", "boundary", "error", "performance"]
    # empty test_kinds → exactly the four
    assert effective_kinds(_plan()) == ["happy", "negative", "boundary", "error"]
    # happy-only (declared in metrics) is the one intentional collapse
    happy_only = TestPlan(id="p", context_id="c", metrics=["happy only"], test_kinds=["performance"])
    assert effective_kinds(happy_only) == ["happy"]


def test_heuristic_keeps_defaults_when_test_kinds_collapsed():
    plan = _plan(test_kinds=["performance"])  # the collapsed state that produced the garbage suite
    scs = heuristic_scenarios(plan, _pack_with("Import ZIP"), [])
    kinds = {s.kind for s in scs}
    assert {"happy", "negative", "boundary", "error"} <= kinds and "performance" in kinds


async def test_implement_session_refuses_without_confirmed_plan(pack_bucket):
    bank = MemoryBank(pack_bucket)  # no define/approve run
    assert ImplementSession(bank, "run-6f2a", seed="run-6f2a").is_empty()
