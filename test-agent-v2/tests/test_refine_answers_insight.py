"""R2 tests: answer ingestion + insight distillation + persistence (the Collect-insight edge)."""

from __future__ import annotations

from dataclasses import asdict

from common.interrogate import (
    assumption_from_self_answer,
    distill_answer,
    ingest,
    load_pack,
)
from common.memory import MemoryBank
from common.models import Answer, Insight, Question, RefinementRun


def _q(qid="Q-biz-1", **kw):
    kw.setdefault("round", "business")
    kw.setdefault("question", "What does 'done' mean?")
    kw.setdefault("options", [{"label": "Accepted", "implication": "x"},
                              {"label": "Materialized", "implication": "y"}])
    kw.setdefault("recommendation", "Materialized")
    return Question(id=qid, **kw)


def test_ingest_line_format_matches_option():
    qs = [_q()]
    res = ingest(qs, "Q-biz-1: Materialized", now="T")
    assert len(res.answers) == 1
    a = res.answers[0]
    assert a.question_id == "Q-biz-1" and a.chosen_option == "Materialized"
    assert qs[0].status == "answered" and not res.carried


def test_ingest_short_label_not_matched_midword():
    """A 2-char option label must not match inside an unrelated word (\"ui\" ⊄ \"build\"/\"suite\")."""
    opts = [{"label": "UI", "implication": "x"}, {"label": "API", "implication": "y"}]
    res = ingest([_q(options=opts)], "Q-biz-1: cover the whole build suite")
    assert res.answers[0].chosen_option == ""                      # no false UI match
    res2 = ingest([_q(options=opts)], "Q-biz-1: use the API here")
    assert res2.answers[0].chosen_option == "API"                  # a real token still maps


def test_ingest_blank_answer_does_not_fabricate_option():
    """INT-04: a blank answer text matches an empty regex against every label — must NOT pick one."""
    res = ingest([_q()], [{"question_id": "Q-biz-1", "text": ""}])
    assert res.answers[0].chosen_option == ""   # blank ≠ the first option ("Accepted")


def test_ingest_json_list_and_new_seed():
    qs = [_q("Q-biz-1"), _q("Q-biz-2")]
    raw = '[{"question_id": "Q-biz-1", "text": "read it", "new_seed": "confluence:999"}]'
    res = ingest(qs, raw)
    assert res.answers[0].new_seed == "confluence:999"
    assert [q.id for q in res.carried] == ["Q-biz-2"]


def test_parse_raw_answers_degrades_on_brace_like_non_json():
    """INT-01: a reply that merely starts with `{`/`[` but isn't valid JSON (or is JSON whose
    `answers` are non-dicts) must parse without raising — not hard-fail the refine/define turn."""
    from common.interrogate.answers import parse_raw_answers
    assert parse_raw_answers("{Q-bus-1: yes}") == {"{Q-bus-1": "yes}"}   # invalid JSON → line parser
    assert parse_raw_answers('{"answers":["yes"]}') == {}                # list of non-dicts → skipped


def test_ingest_seed_marker_in_line():
    res = ingest([_q()], "Q-biz-1: source of truth [seed:confluence:123]")
    assert res.answers[0].new_seed == "confluence:123"
    assert "[seed:" not in res.answers[0].text


def test_ingest_defer_is_flagged_not_dropped():
    qs = [_q()]
    res = ingest(qs, "Q-biz-1: defer")
    assert not res.answers and qs[0].status == "deferred"
    assert res.deferred and res.deferred[0].id == "Q-biz-1"


def test_ingest_unknown_question_ignored():
    res = ingest([_q("Q-biz-1")], "Q-zzz-9: whatever")
    assert not res.answers


def _pack(pack_bucket):
    return load_pack(MemoryBank(pack_bucket), "run-6f2a", seed="LUZ-158390")


def test_distill_human_answer_is_high_confidence_decision(pack_bucket):
    pack = _pack(pack_bucket)
    q = _q(applies_to="jira:LUZ-158390")
    ans = Answer(question_id="Q-biz-1", answered_by="human", chosen_option="Materialized",
                 text="assert per-doc searchable")
    ins = distill_answer(ans, q, pack, run_id="refine-1", now="T")
    assert ins.kind == "decision" and ins.confidence == "high"
    assert ins.source_refs == ["jira:LUZ-158390"]
    assert "Materialized" in ins.statement
    assert "Accepted" in ins.rejected


def test_distill_free_text_answer_rejects_nothing(pack_bucket):
    """INT-05: an option-less (free-text) answer must not mark every option rejected."""
    pack = _pack(pack_bucket)
    ans = Answer(question_id="Q-biz-1", answered_by="human", text="just some free text", chosen_option="")
    ins = distill_answer(ans, _q(), pack, run_id="r")
    assert ins.rejected == []


def test_distill_new_seed_answer_is_gap_seed(pack_bucket):
    pack = _pack(pack_bucket)
    ans = Answer(question_id="Q-biz-1", new_seed="confluence:999", text="read it")
    ins = distill_answer(ans, _q(), pack, run_id="r")
    assert ins.kind == "gap-seed"


def test_self_answer_becomes_low_confidence_assumption(pack_bucket):
    pack = _pack(pack_bucket)
    ins = assumption_from_self_answer(_q(), pack, run_id="r")
    assert ins.kind == "assumption" and ins.answered_by == "agent-self"
    assert ins.confidence == "low"


def test_upsert_insight_roundtrips_and_indexes(fake_bucket):
    bank = MemoryBank(fake_bucket)
    ins = Insight(id="insight:run-6f2a:Q-biz-1", kind="decision", context_id="run-6f2a",
                  question_id="Q-biz-1", statement="done -> materialized",
                  source_refs=["jira:LUZ-158390"])
    path = bank.upsert_insight(ins)
    assert path == "memory/notes/insight/insight_run-6f2a_Q-biz-1.md"
    assert bank.read_insight("insight:run-6f2a:Q-biz-1").statement == "done -> materialized"
    bank.update_index(lambda g: g.add_insight(ins))
    graph, _ = bank.load_index()
    assert "insight:run-6f2a:Q-biz-1" in graph.nodes
    assert any(e["target"] == "jira:LUZ-158390" for e in graph.edges.values())


def test_refine_session_files_and_run_log(fake_bucket):
    bank = MemoryBank(fake_bucket)
    qs = [_q()]
    bank.write_questions("run-6f2a", qs)
    assert bank.read_questions("run-6f2a")[0].id == "Q-biz-1"

    bank.append_answers("run-6f2a", [Answer(question_id="Q-biz-1", text="a1")])
    bank.append_answers("run-6f2a", [Answer(question_id="Q-biz-2", text="a2")])
    assert [a.question_id for a in bank.read_answers("run-6f2a")] == ["Q-biz-1", "Q-biz-2"]

    bank.write_understanding("run-6f2a", "## Understanding\nok")
    assert "Understanding" in bank.read_understanding("run-6f2a")


def test_append_answers_routes_through_cas(fake_bucket, monkeypatch):
    # MEM-04: append is a CAS read-modify-write (mutate_json), not a blind _put, so a concurrent
    # append can't drop an answer.
    bank = MemoryBank(fake_bucket)
    seen: list[str] = []
    real = bank.mutate_json
    monkeypatch.setattr(bank, "mutate_json",
                        lambda path, mutate, **kw: (seen.append(path), real(path, mutate, **kw))[1])
    bank.append_answers("run-x", [Answer(question_id="q1", text="a1")])
    bank.append_answers("run-x", [Answer(question_id="q2", text="a2")])
    assert seen and all(p.endswith("answers.json") for p in seen)
    assert [a.question_id for a in bank.read_answers("run-x")] == ["q1", "q2"]

    path = bank.append_refine_run_log(RefinementRun(
        run_id="9c1b", context_id="run-6f2a", seed="LUZ-158390",
        rounds=["business"], insights_written=1, started="2026-08-27T10-00-00Z"))
    assert path == "memory/runs/2026-08-27T10-00-00Z_refine-9c1b.md"
    assert "Refine run 9c1b" in fake_bucket.store[path]


def test_redactor_applies_to_insight(fake_bucket):
    bank = MemoryBank(fake_bucket, redactor=lambda s: s.replace("SECRET", "<redacted>"))
    bank.upsert_insight(Insight(id="insight:c:Q1", kind="decision", context_id="c",
                                question_id="Q1", statement="holds SECRET value"))
    md = fake_bucket.store["memory/notes/insight/insight_c_Q1.md"]
    assert "SECRET" not in md and "<redacted>" in md


def test_asdict_insight_is_json_native():
    d = asdict(Insight(id="i", kind="decision", context_id="c", question_id="q", statement="s"))
    assert set(d) >= {"id", "kind", "source_refs", "rejected"}
