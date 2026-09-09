"""M1 tests: the define loop — rounds, decisions, TestPlan assembly, resumability, gaps."""

from __future__ import annotations

from common.memory import MemoryBank
from common.testplan import memory as store
from common.testplan.models import ASSUMPTION, CONFIRMED, DRAFT
from test_plan_definition.define import PlanSession, define


async def test_full_pass_confirms_a_plan(pack_bucket):
    bank = MemoryBank(pack_bucket)
    result = await define(bank, "run-6f2a", seed="LUZ-158390")

    plan = result.plan
    assert plan is not None and plan.context_id == "run-6f2a"
    assert plan.methodology == ["api"]
    assert plan.scope
    assert plan.metrics
    assert not result.open_gaps
    assert plan.status == CONFIRMED
    assert result.confidence in ("high", "medium")

    assert store.read_plan(bank, "run-6f2a").methodology == ["api"]
    assert "Test Plan brief" in (store.read_plan_brief(bank, "run-6f2a") or "")
    assert store.read_decisions(bank, "run-6f2a")


async def test_self_answered_becomes_a_vetoable_assumption(pack_bucket):
    bank = MemoryBank(pack_bucket)
    result = await define(bank, "run-6f2a", seed="LUZ-158390")
    kinds = {d.kind for d in result.decisions}
    assert ASSUMPTION in kinds
    assert result.confidence == "medium"


async def test_unanswered_open_question_becomes_a_declared_gap(pack_bucket):
    bank = MemoryBank(pack_bucket)
    session = PlanSession(bank, "run-6f2a", seed="LUZ-158390")
    while (open_qs := session.next_questions()) is not None:
        await session.submit({q.id: "defer" for q in open_qs})
    result = session.finalize()
    assert result.open_gaps
    assert result.plan.status == DRAFT
    assert result.confidence == "low"


async def test_resume_across_turns_via_rehydrate(pack_bucket):
    bank = MemoryBank(pack_bucket)
    s1 = PlanSession(bank, "run-6f2a", seed="LUZ-158390")
    first = s1.next_questions()
    assert first and first[0].round == "methodology"
    await s1.submit({q.id: q.recommendation for q in first})
    s1.save()

    s2 = PlanSession.rehydrate(bank, "run-6f2a")
    assert s2.decisions
    while (open_qs := s2.next_questions()) is not None:
        await s2.submit({q.id: q.recommendation for q in open_qs})
    result = s2.finalize()
    assert result.plan.status == CONFIRMED
    assert result.plan.methodology == ["api"]


async def test_empty_pack_declines(fake_bucket):
    bank = MemoryBank(fake_bucket)
    result = await define(bank, "run-empty")
    assert result.plan is None
    assert "Nothing to plan" in result.brief
