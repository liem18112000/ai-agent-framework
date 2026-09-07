"""M2: the async projector — on_write enqueue (deduped, gcs-gated) + drain into the pg store."""

from __future__ import annotations

from common.memory import MemoryBank
from common.memory.pg.project import INDEX_QUEUE, drain_index, index_on_write
from common.models import Insight, LinkRecord, Note


class _FakeStore:
    def __init__(self):
        self.nodes: dict = {}
        self.edges: list = []
        self.embeds: dict = {}

    async def upsert_node(self, row):
        self.nodes[row["id"]] = row

    async def upsert_edges(self, edges):
        self.edges.extend(edges)

    async def set_embedding(self, node_id, vec):
        self.embeds[node_id] = vec


def _note():
    return Note(
        id="jira:LUZ-1", type="jira-issue", title="Login", synopsis="login flow",
        links=[LinkRecord(source_id="jira:LUZ-1", url="u", type="confluence-page",
                          origin="body", canonical_url="https://c/9", in_scope=True)],
    )


def _bank(fake_bucket) -> MemoryBank:
    return MemoryBank(fake_bucket, on_write=index_on_write)


def test_on_write_noop_under_gcs(fake_bucket, monkeypatch):
    monkeypatch.delenv("MEMORY_BACKEND", raising=False)  # default gcs
    bank = _bank(fake_bucket)
    bank.upsert_note(_note())
    assert bank.get_json(INDEX_QUEUE, []) == []          # nothing enqueued


def test_on_write_enqueues_and_dedups(fake_bucket, monkeypatch):
    monkeypatch.setenv("MEMORY_BACKEND", "hybrid")
    bank = _bank(fake_bucket)
    bank.upsert_note(_note())
    bank.upsert_note(_note())                            # same id again → still one job
    q = bank.get_json(INDEX_QUEUE, [])
    assert len(q) == 1 and q[0]["node_id"] == "jira:LUZ-1"


async def test_drain_projects_note_and_edges(fake_bucket, monkeypatch):
    monkeypatch.setenv("MEMORY_BACKEND", "hybrid")
    bank = _bank(fake_bucket)
    bank.upsert_note(_note())
    store = _FakeStore()
    assert await drain_index(bank, store) == 1
    assert store.nodes["jira:LUZ-1"]["title"] == "Login"
    assert store.nodes["jira:LUZ-1"]["synopsis"] == "login flow"
    assert {e["target"] for e in store.edges} == {"https://c/9"}
    assert bank.get_json(INDEX_QUEUE, []) == []          # cleared after projection
    assert await drain_index(bank, store) == 0           # idempotent — nothing pending


async def test_drain_projects_insight(fake_bucket, monkeypatch):
    monkeypatch.setenv("MEMORY_BACKEND", "postgres")
    bank = _bank(fake_bucket)
    bank.upsert_insight(Insight(
        id="insight:x", kind="lesson", context_id="run-1", question_id="",
        statement="Dunning failCount is day-of-month", source_refs=["jira:LUZ-156281"],
        confidence="high", scope="shared", status="active", origin_step="define",
    ))
    store = _FakeStore()
    assert await drain_index(bank, store) == 1
    row = store.nodes["insight:x"]
    assert row["kind"] == "lesson" and row["scope"] == "shared" and row["status"] == "active"
    assert row["synopsis"].startswith("Dunning")
    assert {e["target"] for e in store.edges} == {"jira:LUZ-156281"}


async def test_drain_survives_a_missing_node(fake_bucket, monkeypatch):
    monkeypatch.setenv("MEMORY_BACKEND", "hybrid")
    bank = _bank(fake_bucket)
    bank.upsert_note(_note())
    # wipe the GCS sidecar so the queued node can't be read back — the job should drop, not hang
    fake_bucket.store.pop("memory/notes/jira-issue/jira_LUZ-1.json", None)
    store = _FakeStore()
    assert await drain_index(bank, store) == 1           # job consumed (node gone → dropped)
    assert store.nodes == {}
    assert bank.get_json(INDEX_QUEUE, []) == []
