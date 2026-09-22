"""M5: backfill derives the pg recall tier from the GCS index (idempotent, resumable)."""

from __future__ import annotations

from common.memory import MemoryBank
from common.memory.pg.backfill import backfill, enqueue_all
from common.memory.pg.project import INDEX_QUEUE
from common.models import Insight, Note


class _FakeStore:
    def __init__(self):
        self.nodes: dict = {}
        self.edges: list = []
        self.ann_built = False

    async def upsert_node(self, row):
        self.nodes[row["id"]] = row

    async def upsert_edges(self, edges):
        self.edges.extend(edges)

    async def set_embedding(self, node_id, vec, *, emb_hash=""):
        pass

    async def ensure_ann_index(self):
        self.ann_built = True


def _seeded_bank(fake_bucket) -> MemoryBank:
    """A bank whose GCS holds two note sidecars + one insight, all present in the index."""
    bank = MemoryBank(fake_bucket)
    note = Note(id="jira:LUZ-1", type="jira-issue", title="Login", synopsis="login flow")
    ins = Insight(id="insight:x", kind="lesson", context_id="run-1", question_id="",
                  statement="Dunning failCount is day-of-month", source_refs=["jira:LUZ-1"])
    bank.upsert_note(note)
    bank.upsert_insight(ins)
    bank.update_index(lambda g: (g.add_note(note), g.add_insight(ins)))
    return bank


async def test_backfill_projects_every_index_node(fake_bucket):
    bank = _seeded_bank(fake_bucket)
    store = _FakeStore()
    total, projected = await backfill(bank, store)
    assert total == 2 and projected == 2
    assert set(store.nodes) == {"jira:LUZ-1", "insight:x"}
    assert store.nodes["insight:x"]["kind"] == "lesson"
    assert bank.get_json(INDEX_QUEUE, []) == []
    assert store.ann_built


async def test_backfill_is_idempotent(fake_bucket):
    bank = _seeded_bank(fake_bucket)
    await backfill(bank, _FakeStore())
    store2 = _FakeStore()
    total, projected = await backfill(bank, store2)
    assert total == 2 and projected == 2
    assert set(store2.nodes) == {"jira:LUZ-1", "insight:x"}


def test_enqueue_all_counts_index_nodes(fake_bucket):
    bank = _seeded_bank(fake_bucket)
    assert enqueue_all(bank) == 2
    assert {j["node_id"] for j in bank.get_json(INDEX_QUEUE, [])} == {"jira:LUZ-1", "insight:x"}
