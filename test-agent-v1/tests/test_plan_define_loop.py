"""M1 tests: the define loop — rounds, decisions, TestPlan assembly, resumability, gaps.

Uses the pack_run-6f2a fixture (a refined pack) as the define input. The heuristic generator
runs (no LLM), so everything here is deterministic.
"""

from __future__ import annotations

from common.memory import MemoryBank
from test_plan_definition import memory as store
from test_plan_definition.define import PlanSession, define
from test_plan_definition.models import ASSUMPTION, CONFIRMED, DRAFT


async def test_full_pass_confirms_a_plan(pack_bucket):
    bank = MemoryBank(pack_bucket)
    result = await define(bank, "run-6f2a", seed="LUZ-158390")

    plan = result.plan
    assert plan is not None and plan.context_id == "run-6f2a"
    assert plan.methodology == ["api"]  # recommended option, taken headlessly
    assert plan.scope  # at least the primary node landed in scope
    assert plan.metrics  # "passed means" settled
    # all open questions answered headlessly -> confirmed, no gaps
    assert not result.open_gaps
    assert plan.status == CONFIRMED
    assert result.confidence in ("high", "medium")

    # persisted: plan.json round-trips, brief + decisions written
    assert store.read_plan(bank, "run-6f2a").methodology == ["api"]
    assert "Test Plan brief" in (store.read_plan_brief(bank, "run-6f2a") or "")
    assert store.read_decisions(bank, "run-6f2a")


async def test_self_answered_becomes_a_vetoable_assumption(pack_bucket):
    bank = MemoryBank(pack_bucket)
    result = await define(bank, "run-6f2a", seed="LUZ-158390")
    kinds = {d.kind for d in result.decisions}
    assert ASSUMPTION in kinds  # the metrics coverage-bar question is self-answered
    # an assumption present but no open gaps -> medium confidence (human-veto pending)
    assert result.confidence == "medium"


async def test_unanswered_open_question_becomes_a_declared_gap(pack_bucket):
    bank = MemoryBank(pack_bucket)
    session = PlanSession(bank, "run-6f2a", seed="LUZ-158390")
    # answer every round by deferring (skip) -> open questions carried as gaps, none settled
    while (open_qs := session.next_questions()) is not None:
        await session.submit({q.id: "defer" for q in open_qs})
    result = session.finalize()
    assert result.open_gaps  # nothing was actually decided
    assert result.plan.status == DRAFT
    assert result.confidence == "low"


async def test_resume_across_turns_via_rehydrate(pack_bucket):
    bank = MemoryBank(pack_bucket)
    # turn 1: start, answer the first round, pause (save)
    s1 = PlanSession(bank, "run-6f2a", seed="LUZ-158390")
    first = s1.next_questions()
    assert first and first[0].round == "methodology"
    await s1.submit({q.id: q.recommendation for q in first})
    s1.save()

    # turn 2: a fresh process rehydrates and finishes the remaining rounds
    s2 = PlanSession.rehydrate(bank, "run-6f2a")
    assert s2.decisions  # the methodology decision survived the pause
    while (open_qs := s2.next_questions()) is not None:
        await s2.submit({q.id: q.recommendation for q in open_qs})
    result = s2.finalize()
    assert result.plan.status == CONFIRMED
    assert result.plan.methodology == ["api"]


async def test_empty_pack_declines(fake_bucket):
    bank = MemoryBank(fake_bucket)  # nothing gathered
    result = await define(bank, "run-empty")
    assert result.plan is None
    assert "Nothing to plan" in result.brief
