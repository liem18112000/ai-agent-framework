"""Integration test — the full self-learning lifecycle end-to-end (L0–L6), real functions.

Two runs over one shared GCS memory bank: run A finishes and its human decisions are enqueued;
a drain distils them into durable lessons; run B on the same seed recalls them (grounded) and they
surface in the pack the interrogation reads; a veto retracts one and recall drops it. Nothing in the
learn path is mocked — this drives the real capture → queue → drain → recall → govern flow.
"""

from __future__ import annotations

from dataclasses import asdict

from common.learn import (
    CaptureJob,
    drain,
    enqueue,
    from_decisions,
    recall_lessons,
    search_lessons,
    veto_lesson,
)
from common.memory import MemoryBank
from common.models import Insight, Pack
from tests.conftest import FakeBucket


def _seed_bank() -> MemoryBank:
    """A bank whose index holds the seed's gathered nodes, so lessons citing them are grounded."""
    bank = MemoryBank(FakeBucket())
    for nid, title in [("jira:LUZ-156281", "Credit-only billing"), ("jira:LUZ-159312", "Test plan")]:
        bank.update_index(lambda g, nid=nid, title=title:
                          g.nodes.__setitem__(nid, {"id": nid, "type": "jira-issue", "title": title}))
    return bank


def test_self_learning_end_to_end():
    bank = _seed_bank()

    # --- Run A: refine finishes → its human decisions are captured (as refine.py wires it) --- #
    decisions = [
        Insight(id="insight:run-A:Q1", kind="decision", context_id="run-A", question_id="Q1",
                statement="Performance targets the credit-only operation, not file import",
                answered_by="human", source_refs=["jira:LUZ-159312"], rejected=["file import"],
                confidence="high"),
        Insight(id="insight:run-A:Q2", kind="assumption", context_id="run-A", question_id="Q2",
                statement="an agent-self guess", answered_by="agent-self",
                source_refs=["jira:LUZ-159312"]),
    ]
    enqueue(bank, CaptureJob(id="cap-run-A", context_id="run-A", run_id="run-A", step="refine",
                             signals=[asdict(s) for s in from_decisions(decisions)]))
    assert search_lessons(bank) == []  # queued off the request path — not captured yet

    # --- Between runs: the background drain distils the queued job into a durable lesson --- #
    assert drain(bank) == 1
    lessons = search_lessons(bank)
    assert len(lessons) == 1  # only the HUMAN decision, not the agent-self assumption
    assert lessons[0]["kind"] == "correction"  # it rejected an option
    lesson_id = lessons[0]["id"]

    # --- Run B: a new run on the same seed recalls the lesson (grounded) and reads it in the pack --- #
    recalled = recall_lessons(bank, seed_refs={"jira:LUZ-159312", "jira:LUZ-156281"})
    assert recalled == ["Performance targets the credit-only operation, not file import"]
    pack = Pack(context_id="run-B", seed="LUZ-159312", lessons=recalled)
    assert "Prior lessons" in pack.summary_text() and "credit-only operation" in pack.summary_text()

    # an UNRELATED seed does NOT recall it — B5 grounding stops the memory-bias bleed
    assert recall_lessons(bank, seed_refs={"jira:OTHER-1"}) == []

    # --- Governance: a human veto retracts the lesson → gone from recall + search, never re-learned --- #
    assert veto_lesson(bank, lesson_id) is True
    assert recall_lessons(bank, seed_refs={"jira:LUZ-159312"}) == []
    assert search_lessons(bank) == []

    # re-capturing the same decision must NOT resurrect a vetoed lesson
    enqueue(bank, CaptureJob(id="cap-run-A2", context_id="run-A", step="refine",
                             signals=[asdict(s) for s in from_decisions(decisions)]))
    drain(bank)
    assert search_lessons(bank) == []
