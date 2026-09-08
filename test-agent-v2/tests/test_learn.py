"""L1 tests: self-learning capture + durable queue."""

from __future__ import annotations

from dataclasses import asdict

from common.learn import (
    QUEUE_PATH,
    CaptureJob,
    LessonSignal,
    capture_lessons,
    drain,
    enqueue,
    from_decisions,
    from_gather,
    from_implement,
    recall_lessons,
    search_lessons,
    veto_lesson,
)
from common.memory import MemoryBank
from common.models import CORRECTION, Insight
from tests.conftest import FakeBucket


def _bank_with_node(node_id: str = "jira:LUZ-1") -> MemoryBank:
    """A bank whose index holds one real node, so a lesson citing it is grounded."""
    bank = MemoryBank(FakeBucket())
    bank.update_index(
        lambda g: g.nodes.__setitem__(node_id, {"id": node_id, "type": "jira-issue", "title": "x"}))
    return bank


def _insight_ids(bank) -> list[str]:
    graph, _ = bank.load_index()
    return [n for n in graph.nodes if n.startswith("insight:")]


def test_capture_persists_grounded_lesson():
    bank = _bank_with_node()
    sig = LessonSignal(statement="QR fallback removal is individual-only, not company",
                       kind=CORRECTION, source_refs=["jira:LUZ-1"], confidence="high")
    kept = capture_lessons(bank, context_id="run-1", run_id="run-1", step="review", signals=[sig])

    assert len(kept) == 1
    ins = kept[0]
    assert ins.kind == "correction" and ins.origin_step == "review" and ins.confidence == "high"
    assert ins.scope == "context" and ins.status == "active"
    assert bank.read_insight(ins.id) is not None
    assert ins.id in _insight_ids(bank)


def test_capture_drops_ungrounded_lesson():
    bank = _bank_with_node()
    sig = LessonSignal(statement="a hallucinated fact", source_refs=["jira:DOES-NOT-EXIST"])
    assert capture_lessons(bank, context_id="run-1", signals=[sig]) == []
    assert _insight_ids(bank) == []


def test_capture_allows_when_index_empty():
    bank = MemoryBank(FakeBucket())
    kept = capture_lessons(bank, context_id="run-1", signals=[LessonSignal(statement="first lesson")])
    assert len(kept) == 1


def test_capture_is_idempotent():
    bank = _bank_with_node()
    sig = LessonSignal(statement="the same lesson", source_refs=["jira:LUZ-1"])
    first = capture_lessons(bank, context_id="run-1", signals=[sig])
    second = capture_lessons(bank, context_id="run-1", signals=[sig])
    assert len(first) == 1 and second == []
    assert len(_insight_ids(bank)) == 1


def test_vetoed_lesson_is_not_relearned():
    bank = _bank_with_node()
    sig = LessonSignal(statement="a lesson later judged wrong", source_refs=["jira:LUZ-1"])
    ins = capture_lessons(bank, context_id="run-1", signals=[sig])[0]

    ins.status = "vetoed"
    bank.upsert_insight(ins)

    assert capture_lessons(bank, context_id="run-1", signals=[sig]) == []


def test_queue_enqueue_and_drain():
    bank = _bank_with_node()
    job = CaptureJob(id="j1", context_id="run-1", run_id="run-1", step="refine",
                     signals=[asdict(LessonSignal(statement="lesson from refine",
                                                  source_refs=["jira:LUZ-1"]))])
    enqueue(bank, job)
    assert len(bank.get_json(QUEUE_PATH, [])) == 1

    assert drain(bank) == 1
    assert bank.get_json(QUEUE_PATH, []) == []
    assert len(_insight_ids(bank)) == 1


def test_queue_drain_is_idempotent_and_accumulates():
    bank = _bank_with_node()
    for i in range(3):
        enqueue(bank, CaptureJob(id=f"j{i}", context_id="run-1", step="refine",
                                 signals=[asdict(LessonSignal(statement=f"lesson {i}",
                                                              source_refs=["jira:LUZ-1"]))]))
    assert drain(bank) == 3
    assert drain(bank) == 0
    assert len(_insight_ids(bank)) == 3


def test_from_decisions_captures_human_choices_only():
    human = Insight(id="i1", kind="decision", context_id="c", question_id="q1",
                    statement="Test end-to-end through real controller chains", answered_by="human",
                    source_refs=["jira:LUZ-1"], rejected=["Unit only"], confidence="high")
    assumption = Insight(id="i2", kind="assumption", context_id="c", question_id="q2",
                         statement="Assume sandbox exists", answered_by="agent-self",
                         source_refs=["jira:LUZ-1"])
    sigs = from_decisions([human, assumption])
    assert len(sigs) == 1
    assert sigs[0].kind == CORRECTION
    assert sigs[0].source_refs == ["jira:LUZ-1"] and sigs[0].confidence == "high"


def test_recall_lessons_grounded_to_seed():
    bank = _bank_with_node("jira:LUZ-1")
    capture_lessons(bank, context_id="run-1", signals=[
        LessonSignal(statement="lesson about LUZ-1", source_refs=["jira:LUZ-1"], confidence="high")])
    assert recall_lessons(bank, seed_refs={"jira:LUZ-1"}) == ["lesson about LUZ-1"]
    assert recall_lessons(bank, seed_refs={"jira:OTHER"}) == []
    assert recall_lessons(bank, seed_refs=set()) == []


def test_search_and_veto_lessons():
    bank = _bank_with_node("jira:LUZ-1")
    sig = LessonSignal(statement="a governable lesson", source_refs=["jira:LUZ-1"])
    ins = capture_lessons(bank, context_id="run-1", signals=[sig])[0]
    assert len(search_lessons(bank)) == 1
    assert ins.id in _insight_ids(bank)

    assert veto_lesson(bank, ins.id) is True
    assert search_lessons(bank) == []
    assert recall_lessons(bank, seed_refs={"jira:LUZ-1"}) == []
    assert ins.id not in _insight_ids(bank)
    assert capture_lessons(bank, context_id="run-1", signals=[sig]) == []
    assert ins.id not in _insight_ids(bank)
    assert veto_lesson(bank, "insight:nope") is False


def test_from_gather_uses_clean_slug_and_grounds_on_codegraph():
    sigs = from_gather(["axonivy-prod/luz_finance"], seed_ref="jira:LUZ-159312")
    assert len(sigs) == 1
    assert sigs[0].statement == "jira:LUZ-159312 is implemented in repo axonivy-prod/luz_finance"
    assert sigs[0].source_refs == ["jira:LUZ-159312", "codegraph:axonivy-prod/luz_finance"]
    assert from_gather([], seed_ref="jira:LUZ-1") == []


def test_from_implement_one_bounded_coverage_lesson():
    from types import SimpleNamespace
    scs = [SimpleNamespace(kind="happy", source_refs=["jira:LUZ-1"]),
           SimpleNamespace(kind="negative", source_refs=["jira:LUZ-1"]),
           SimpleNamespace(kind="negative", source_refs=["insight:x"])]
    sigs = from_implement(scs, context_id="run-1")
    assert len(sigs) == 1
    assert "3 scenarios" in sigs[0].statement
    assert "1 happy" in sigs[0].statement and "2 negative" in sigs[0].statement
    assert set(sigs[0].source_refs) == {"jira:LUZ-1", "insight:x"}
    assert from_implement([], context_id="run-1") == []
