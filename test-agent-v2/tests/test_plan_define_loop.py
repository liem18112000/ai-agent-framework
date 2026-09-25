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


async def test_rehydrate_re_reads_the_pack_rather_than_trusting_the_checkpoint(pack_bucket):
    """R3: 'editing a file is not delivery' — a resumed seat that never re-reads disk acts on stale
    intent. Our checkpoint carries only progress (pending rounds, decisions, answers); the
    intent-bearing pack is re-read from the bank by the ctor on every rehydrate. PIN that: a note
    added to the bank mid-session must be visible to the resumed session. If a future refactor
    caches the pack into the checkpoint for speed, this fails — which is the point."""
    from common.models import Note

    bank = MemoryBank(pack_bucket)
    s1 = PlanSession(bank, "run-6f2a", seed="LUZ-158390")
    before = {n.id for n in s1.plan_pack.pack.grounded}
    s1.save()

    # the world moves while the session is parked (a later gather, a new AC). load_pack scopes by
    # run_id AND reads the index, so a realistic arrival needs both — a bare upsert_note is invisible.
    mid = Note(id="jira:MID-SESSION", type="note", title="arrived after the checkpoint",
               run_id="run-6f2a")
    bank.upsert_note(mid)
    bank.update_index(lambda g: g.nodes.__setitem__(
        mid.id, {"id": mid.id, "type": mid.type, "title": mid.title}))

    s2 = PlanSession.rehydrate(bank, "run-6f2a")
    after = {n.id for n in s2.plan_pack.pack.grounded}
    assert "jira:MID-SESSION" not in before
    assert "jira:MID-SESSION" in after, "resume must re-read intent from the bank, not the checkpoint"


async def test_empty_pack_declines(fake_bucket):
    bank = MemoryBank(fake_bucket)
    result = await define(bank, "run-empty")
    assert result.plan is None
    assert "Nothing to plan" in result.brief
