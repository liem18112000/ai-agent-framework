"""Admin utility — offline tests for the A0 enabler + F1–F4 handlers (InMemoryObjectStore, no DB)."""

from __future__ import annotations

import datetime
import json

from common import admin
from common.memory import MemoryBank
from common.models import LESSON, Answer, Insight, Note, Question
from common.store.memory import InMemoryObjectStore


def _bank() -> MemoryBank:
    return MemoryBank(InMemoryObjectStore())


def _seed_run(bank: MemoryBank, ctx: str, *, seed: str, now: str, done: bool = True,
              questions: int = 0, answers: int = 0, understanding: str | None = None) -> None:
    bank.write_refine_state(ctx, {"seed": seed, "now": now, "done": done, "pending": []})
    if questions:
        bank.write_questions(ctx, [Question(id=f"q{i}", round="business", question=f"Q{i}?")
                                   for i in range(questions)])
    if answers:
        bank.append_answers(ctx, [Answer(question_id=f"q{i}", text="a") for i in range(answers)])
    if understanding is not None:
        bank.write_understanding(ctx, understanding)


def _add_note(bank: MemoryBank, note: Note) -> None:
    bank.upsert_note(note)
    bank.update_index(lambda g: g.add_note(note))


def _add_lesson(bank: MemoryBank, ins: Insight) -> None:
    bank.upsert_insight(ins)
    bank.update_index(lambda g: g.add_insight(ins))


# --- A0: the ObjectStore port extension ------------------------------------------------------------

def test_iter_blobs_by_prefix_and_delete_idempotent():
    store = InMemoryObjectStore()
    for k in ("memory/a.json", "memory/sub/b.json", "other/c.json"):
        store.blob(k).upload_from_string("x")
    assert sorted(b.name for b in store.iter_blobs("memory/")) == ["memory/a.json", "memory/sub/b.json"]
    assert sorted(b.name for b in store.iter_blobs("")) == ["memory/a.json", "memory/sub/b.json", "other/c.json"]
    assert store.delete("memory/a.json") is True
    assert store.delete("memory/a.json") is False  # idempotent


def test_delete_prefix_returns_count_and_spares_backups():
    bank = _bank()
    store = bank._bucket
    store.blob("memory/x.json").upload_from_string("1")
    store.blob("memory/y.json").upload_from_string("2")
    store.blob("memory-backups/v1/MANIFEST.json").upload_from_string("{}")
    assert bank.delete_prefix("memory/") == 2
    assert "memory-backups/v1/MANIFEST.json" in store.store  # trailing-slash prefix spares backups


# --- F1: run history -------------------------------------------------------------------------------

def test_list_runs_newest_first_with_counts():
    bank = _bank()
    _seed_run(bank, "run-old", seed="LUZ-1", now="2026-01-01T00-00-00Z", questions=2, answers=1)
    _seed_run(bank, "run-new", seed="LUZ-2", now="2026-02-01T00-00-00Z", questions=3, answers=3)
    out = admin.list_runs(bank)
    assert out.index("run-new") < out.index("run-old")  # newest first
    assert "1/2" in out and "3/3" in out  # answered/asked counts


def test_get_run_composes_understanding_qa_pack():
    bank = _bank()
    ctx = "run-x"
    _seed_run(bank, ctx, seed="LUZ-9", now="2026-01-01T00-00-00Z",
              questions=1, answers=1, understanding="The confirmed understanding.")
    _add_note(bank, Note(id="jira:LUZ-9", type="jira-issue", title="ticket", run_id=ctx))
    _add_lesson(bank, Insight(id="ins:1", kind=LESSON, context_id=ctx, question_id="q0",
                              statement="always check the dunning day"))
    out = admin.get_run(bank, ctx)
    assert "The confirmed understanding." in out
    assert "1 nodes" in out and "jira-issue" in out
    assert "always check the dunning day" in out
    assert "Q&A (1/1 answered)" in out
    assert out.count("_none_") == 1  # run logs empty → one "_none_"; lessons present → not duplicated


def test_get_run_unknown_context_is_clean_message():
    out = admin.get_run(_bank(), "run-nope")
    assert "No such run" in out and "run-nope" in out


# --- F2: memory introspection ----------------------------------------------------------------------

async def test_view_memory_all_degrades_without_db():
    bank = _bank()
    _seed_run(bank, "run-a", seed="LUZ-1", now="2026-01-01T00-00-00Z", understanding="brief")
    out = await admin.view_memory(bank, None, "all", "run-a")
    assert "Working (in-context)" in out
    assert "Episodic" in out and "in-memory, no DB configured" in out
    assert "Semantic" in out and "no DB configured" in out
    assert "Procedural" in out


async def test_view_memory_procedural_lists_tool_names():
    out = await admin.view_memory(_bank(), None, "procedural")
    for tool in ("gather_knowledge", "define_plan", "evaluate_pack", "wipe_all"):
        assert tool in out
    assert "interrogation rounds:" in out


async def test_view_memory_working_needs_context():
    out = await admin.view_memory(_bank(), None, "working")
    assert "Provide a context_id" in out


# --- F3: wipe-all ----------------------------------------------------------------------------------

async def test_wipe_all_refuses_without_token():
    out = await admin.wipe_all(_bank(), None, "", required_token="WIPE")
    assert "REFUSED" in out and "'WIPE'" in out


async def test_wipe_all_clears_bank_but_keeps_backups_and_is_idempotent():
    bank = _bank()
    _seed_run(bank, "run-a", seed="LUZ-1", now="2026-01-01T00-00-00Z", understanding="brief")
    admin.backup_memory(bank, "safety", now=datetime.datetime(2026, 1, 2, tzinfo=datetime.UTC))

    first = await admin.wipe_all(bank, None, "WIPE", required_token="WIPE")
    assert "blobs removed" in first
    assert not any(k.startswith("memory/") for k in bank._bucket.store)
    assert any(k.startswith("memory-backups/") for k in bank._bucket.store)
    assert "in-memory, nothing persisted" in first  # no-DB task/session report

    second = await admin.wipe_all(bank, None, "WIPE", required_token="WIPE")
    assert "0 blobs removed" in second  # idempotent


# --- F4: backup ------------------------------------------------------------------------------------

def test_backup_copies_all_blobs_and_writes_manifest():
    bank = _bank()
    _seed_run(bank, "run-a", seed="LUZ-1", now="2026-01-01T00-00-00Z", understanding="brief")
    live = {k for k in bank._bucket.store if k.startswith("memory/")}
    out = admin.backup_memory(bank, "snap one", now=datetime.datetime(2026, 1, 2, tzinfo=datetime.UTC))
    assert "Backed up" in out
    version = "2026-01-02T00-00-00Z_snap_one"
    for k in live:
        assert f"memory-backups/{version}/{k}" in bank._bucket.store
    manifest = json.loads(bank._bucket.store[f"memory-backups/{version}/MANIFEST.json"])
    assert manifest["blob_count"] == len(live)
    assert manifest["summary"] == "snap one" and manifest["source_prefix"] == "memory/"


def test_two_backups_are_distinct_versions_listed_newest_first():
    bank = _bank()
    _seed_run(bank, "run-a", seed="LUZ-1", now="2026-01-01T00-00-00Z", understanding="brief")
    admin.backup_memory(bank, "first", now=datetime.datetime(2026, 1, 2, tzinfo=datetime.UTC))
    admin.backup_memory(bank, "second", now=datetime.datetime(2026, 3, 4, tzinfo=datetime.UTC))
    out = admin.list_backups(bank)
    assert "Backups (2)" in out
    assert out.index("second") < out.index("first")  # newest first
