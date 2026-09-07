"""R3 tests: the understanding brief + deterministic confidence roll-up."""

from __future__ import annotations

from common.interrogate import load_pack, restate
from common.memory import MemoryBank
from common.models import Insight, Question


def _pack(pack_bucket):
    return load_pack(MemoryBank(pack_bucket), "run-6f2a", seed="LUZ-158390")


def _decision(qid="Q-biz-1", conf="high"):
    return Insight(id=f"insight:run-6f2a:{qid}", kind="decision", context_id="run-6f2a",
                   question_id=qid, statement=f"{qid} settled", confidence=conf,
                   source_refs=["jira:LUZ-158390"])


def test_brief_lists_decisions_and_problem(pack_bucket):
    md, confidence = restate(_pack(pack_bucket), [_decision()])
    assert "Understanding — LUZ-158390" in md
    assert "Q-biz-1 settled" in md
    assert "Import a conformant" in md or "import" in md.lower()  # problem from the pack synopsis
    assert confidence == "high"


def test_open_questions_drive_low_confidence_and_gaps(pack_bucket):
    opens = [Question(id="Q-qa-1", round="qa", question="Coverage bar?")]
    md, confidence = restate(_pack(pack_bucket), [_decision()], open_questions=opens)
    assert confidence == "low"
    assert "Coverage bar?" in md and "Open gaps" in md


def test_agent_assumptions_yield_medium_confidence(pack_bucket):
    _md, confidence = restate(_pack(pack_bucket), [_decision(conf="low")])
    assert confidence == "medium"  # unconfirmed agent assumption, but nothing open


def test_deferred_shown_separately(pack_bucket):
    deferred = [Question(id="Q-qa-2", round="qa", question="Fuzz malformed ZIPs?", status="deferred")]
    md, _ = restate(_pack(pack_bucket), [_decision()], deferred=deferred)
    assert "Deferred" in md and "Fuzz malformed ZIPs?" in md


def test_custom_understander_is_used(pack_bucket):
    md, _conf = restate(_pack(pack_bucket), [_decision()],
                       understander=lambda p, i, o, d, c: f"BRIEF conf={c}")
    assert md == "BRIEF conf=high"
