"""R1 tests: question generation — pack loading, heuristic rounds, ranking, cap, altitude."""

from __future__ import annotations

from common.interrogate import Pack, generate_round, load_pack
from common.memory import MemoryBank
from common.models import Question

# phrasing that would mean a question dropped below module/service altitude
_IMPL_DETAIL = ["field name", "call order", "config format", "method signature", "payload", "column name"]


def test_load_pack_from_bank(pack_bucket):
    pack = load_pack(MemoryBank(pack_bucket), "run-6f2a")
    ids = {n.id for n in pack.grounded}
    assert ids == {"jira:LUZ-158390", "confluence:49662787598"}
    assert not pack.is_empty()
    # the bitbucket link on the issue was recorded, not followed
    assert "bitbucket" in pack.recorded_only_types()


def test_summary_text_mentions_nodes_and_recorded_only(pack_bucket):
    pack = load_pack(MemoryBank(pack_bucket), "run-6f2a")
    text = pack.summary_text()
    assert "LUZ-158390" in text and "perf comparison" in text
    assert "recorded-only" in text and "bitbucket" in text


def test_heuristic_business_round_asks_done_semantics_and_gaps(pack_bucket):
    pack = load_pack(MemoryBank(pack_bucket), "run-6f2a", seed="LUZ-158390")
    pack.gaps = ["confluence:99999999"]
    qs = generate_round(pack, "business")
    assert all(q.round == "business" for q in qs)
    assert any("done" in q.question.lower() for q in qs)  # pass/fail semantics
    assert any("99999999" in q.question for q in qs)  # the gap became a question
    for q in qs:  # every surfaced question is a real fork with options + a recommendation
        assert q.options and q.recommendation


def test_heuristic_technical_round_env_and_recorded_only(pack_bucket):
    pack = load_pack(MemoryBank(pack_bucket), "run-6f2a")
    qs = generate_round(pack, "technical")
    assert any("environment" in q.question.lower() or "tenant" in q.question.lower() for q in qs)
    assert any("bitbucket" in q.question.lower() for q in qs)  # recorded-only → scope question


def test_heuristic_qa_round_coverage_bar(pack_bucket):
    pack = load_pack(MemoryBank(pack_bucket), "run-6f2a")
    qs = generate_round(pack, "qa")
    assert any("coverage" in q.question.lower() for q in qs)


def test_no_question_below_altitude(pack_bucket):
    pack = load_pack(MemoryBank(pack_bucket), "run-6f2a")
    pack.gaps = ["confluence:99999999"]
    for rnd in ("business", "technical", "qa"):
        for q in generate_round(pack, rnd):
            low = q.question.lower()
            assert not any(bad in low for bad in _IMPL_DETAIL), f"too detailed: {q.question}"


def test_ranking_orders_dependencies_first():
    q1 = Question(id="Q-biz-1", round="business", question="root")
    q2 = Question(id="Q-biz-2", round="business", question="depends", depends_on=["Q-biz-1"])
    pack = Pack(context_id="x")
    out = generate_round(pack, "business", generator=lambda p, r: [q2, q1])  # given out of order
    assert [q.id for q in out] == ["Q-biz-1", "Q-biz-2"]


def test_cap_defers_excess_open_questions():
    many = [Question(id=f"Q-biz-{i}", round="business", question=f"q{i}") for i in range(9)]
    pack = Pack(context_id="x")
    out = generate_round(pack, "business", max_questions=7, generator=lambda p, r: many)
    assert sum(q.status == "open" for q in out) == 7
    assert sum(q.status == "deferred" for q in out) == 2  # excess deferred, not dropped
    assert len(out) == 9  # nothing dropped
