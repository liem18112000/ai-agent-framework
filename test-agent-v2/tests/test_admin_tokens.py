"""Admin token accounting (F5): usage overall / by run / by agent, the estimate, and the lesson.

The load-bearing case here is `persist_usage` ACCUMULATING. A run is chunked across several MCP
calls that each land on a different Cloud Run instance with empty counters, so an overwrite would
silently keep only the last chunk — and a token report that under-reports is worse than none.
"""

from __future__ import annotations

import pytest

from common import admin
from common.admin import tokens as token_admin
from common.llm import meter
from common.memory import MemoryBank
from common.models import Note


@pytest.fixture(autouse=True)
def _clean_meter():
    meter.reset()
    yield
    meter.reset()


@pytest.fixture
def bank():
    # InMemoryObjectStore, not conftest's FakeBucket: these handlers list by prefix (`iter_blobs`,
    # the same idiom runs.py/backup.py use) and FakeBucket implements only blob()/get_blob().
    from common.store.memory import InMemoryObjectStore

    return MemoryBank(InMemoryObjectStore())


def _spend(run_id: str, label: str, **kw):
    with meter.run_scope(run_id):
        meter.record(label, **kw)


def test_run_scope_attributes_spend_to_its_run():
    _spend("ctx-a", "define.brief", input=100, output=10)
    _spend("ctx-b", "gather.distill", input=50, output=5)

    assert meter.snapshot("ctx-a")["TOTAL"]["input"] == 100
    assert meter.snapshot("ctx-b")["TOTAL"]["input"] == 50
    assert meter.snapshot()["TOTAL"]["input"] == 150   # None = every run
    assert meter.runs() == ["ctx-a", "ctx-b"]


def test_persist_accumulates_across_chunked_calls(bank):
    """The assured loop pauses and resumes; each resume is a fresh process with empty counters."""
    _spend("ctx", "tpd_scenario_gen", input=100, output=20, cache_write=800)
    token_admin.persist_usage(bank, "ctx")

    meter.reset()  # a new Cloud Run instance picks up the run
    _spend("ctx", "tpd_scenario_gen", input=120, output=30, cache_read=800)
    stored = token_admin.persist_usage(bank, "ctx")

    row = stored["tpd_scenario_gen"]
    assert row["calls"] == 2 and row["input"] == 220 and row["output"] == 50
    assert row["cache_write"] == 800 and row["cache_read"] == 800
    assert stored["TOTAL"]["input"] == 220  # TOTAL recomputed, never accumulated


def test_usage_overall_spans_runs_and_by_run_narrows(bank):
    for run, label, n in (("ctx-a", "define.brief", 100), ("ctx-b", "gather.distill", 40)):
        _spend(run, label, input=n)
        token_admin.persist_usage(bank, run)
    meter.reset()

    overall = admin.token_usage(bank)
    assert "define.brief" in overall and "gather.distill" in overall
    assert "2 stored run(s)" in overall

    one = admin.token_usage(bank, "ctx-a")
    assert "define.brief" in one and "gather.distill" not in one


def test_by_agent_accepts_several_run_ids(bank):
    for run in ("ctx-a", "ctx-b", "ctx-c"):
        _spend(run, f"agent-{run}", input=10)
        token_admin.persist_usage(bank, run)
    meter.reset()

    both = admin.token_by_agent(bank, ["ctx-a", "ctx-b"])
    assert "agent-ctx-a" in both and "agent-ctx-b" in both and "agent-ctx-c" not in both
    assert "agent-ctx-c" in admin.token_by_agent(bank, [])  # no ids = every run


def test_low_cache_hit_is_called_out(bank):
    _spend("ctx", "tpd_scenario_gen", input=10, cache_write=1000, cache_read=0)
    token_admin.persist_usage(bank, "ctx")
    assert "WARNING: cache-hit under 20%" in admin.token_usage(bank, "ctx")


def test_usage_is_honest_when_nothing_was_recorded(bank):
    assert "nothing recorded" in admin.token_usage(bank, "ctx-missing")
    assert "nothing recorded yet" in admin.token_usage(bank)


def test_estimate_scales_with_the_pack_and_needs_one(bank):
    assert "pack is empty" in admin.estimate_usage(bank, "ctx-empty")

    for i in range(7):
        note = Note(id=f"jira:X-{i}", type="jira", title=f"N{i}", synopsis="s" * 400, run_id="ctx")
        bank.upsert_note(note)
        bank.update_index(lambda g, n=note: g.add_note(n))

    # A confirmed understanding is what makes the TPD prefix differ from the KGA one (PlanPack
    # prepends it). Without it the two prefixes are byte-identical and correctly share ONE entry.
    bank.write_understanding("ctx", "The feature uploads a zip and imports its documents.")

    small = admin.estimate_usage(bank, "ctx", assured_rounds=1)
    big = admin.estimate_usage(bank, "ctx", assured_rounds=4)
    assert "7 grounded unit(s)" in small and "3 generation batch(es)" in small  # ceil(7/3)
    assert "TOTAL (billed-equivalent)" in small
    # more assured rounds = more generation + judge calls = a bigger projection
    assert _total_of(big) > _total_of(small)

    # The cache WRITE is charged once per distinct prefix, not once per stage: every TPD stage
    # shares one pack_block(summary), so they share one entry. Charging it per stage overstated the
    # bill by ~4x the prefix. The FIRST TPD stage pays the write; the later ones only read.
    def write_col(stage: str) -> int:
        line = next(line for line in small.splitlines() if line.startswith(stage))
        return int(line.split()[-1])

    assert write_col("define rounds + brief") > 0     # first stage on the TPD prefix — pays it
    assert write_col("implement generate") == 0       # same prefix, already written
    assert write_col("implement judge") == 0
    assert write_col("gather.distill") == 0           # no prefix at all (nothing to cache)


def _total_of(report: str) -> int:
    line = next(line for line in report.splitlines() if line.startswith("~"))
    return int(line[1:].split()[0])


def test_token_lesson_goes_through_the_normal_lesson_store(bank):
    note = Note(id="jira:X-1", type="jira", title="N", synopsis="s", run_id="ctx")
    bank.upsert_note(note)
    bank.update_index(lambda g: g.add_note(note))

    out = admin.record_token_lesson(
        bank, "ctx", "Pass the pack as cache_prefix, never inline it twice in one call.",
        source_refs=["jira:X-1"])
    assert "token-lesson recorded" in out

    # it is an ordinary Insight lesson, so the existing recall/govern machinery sees it
    from common.learn import search_lessons

    found = search_lessons(bank, "cache_prefix")
    assert any(i["kind"] == token_admin.TOKEN_LESSON for i in found), found

    assert "provide the lesson text" in admin.record_token_lesson(bank, "ctx", "   ")
