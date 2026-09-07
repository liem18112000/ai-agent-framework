"""M3: the projector embeds via the injected embedder, with a content-hash skip on re-projects."""

from __future__ import annotations

from common.memory import MemoryBank
from common.memory.pg import embed, project
from common.models import Note


class _Store:
    """Records upserts + embed calls; embedding_fresh mirrors the real meta->>'emb_hash' check."""

    def __init__(self):
        self.rows: dict = {}         # id -> {"vec", "emb_hash"}
        self.embeds: list = []       # (id, emb_hash) per set_embedding

    async def upsert_node(self, row):
        self.rows.setdefault(row["id"], {})

    async def upsert_edges(self, edges):
        pass

    async def embedding_fresh(self, node_id, emb_hash):
        r = self.rows.get(node_id, {})
        return r.get("vec") is not None and r.get("emb_hash") == emb_hash

    async def set_embedding(self, node_id, vec, *, emb_hash=""):
        self.rows.setdefault(node_id, {}).update({"vec": vec, "emb_hash": emb_hash})
        self.embeds.append((node_id, emb_hash))


async def _stub_embed(texts):  # batch embedder: list[str] -> list[list[float]]
    return [[0.1, 0.2, 0.3] for _ in texts]


def _note(synopsis="login flow"):
    return Note(id="jira:LUZ-1", type="jira-issue", title="Login", synopsis=synopsis)


def _bank(fake_bucket):
    return MemoryBank(fake_bucket, on_write=project.index_on_write)


async def test_drain_embeds_then_skips_unchanged(fake_bucket, monkeypatch):
    monkeypatch.setenv("MEMORY_BACKEND", "hybrid")
    bank = _bank(fake_bucket)
    store = _Store()
    bank.upsert_note(_note())
    await project.drain_index(bank, store, embedder=_stub_embed)
    assert store.rows["jira:LUZ-1"]["vec"] == [0.1, 0.2, 0.3]
    assert len(store.embeds) == 1
    # re-project the SAME unchanged node → content-hash fresh → no second embed call
    project.enqueue_index(bank, "jira:LUZ-1", "jira-issue")
    await project.drain_index(bank, store, embedder=_stub_embed)
    assert len(store.embeds) == 1


async def test_drain_reembeds_on_changed_text(fake_bucket, monkeypatch):
    monkeypatch.setenv("MEMORY_BACKEND", "hybrid")
    bank = _bank(fake_bucket)
    store = _Store()
    bank.upsert_note(_note("login flow"))
    await project.drain_index(bank, store, embedder=_stub_embed)
    bank.upsert_note(_note("login flow — reworded"))   # merge_notes keeps the newer synopsis
    await project.drain_index(bank, store, embedder=_stub_embed)
    assert len(store.embeds) == 2                       # text changed → re-embedded


async def test_no_embedder_projects_metadata_only(fake_bucket, monkeypatch):
    monkeypatch.setenv("MEMORY_BACKEND", "hybrid")
    bank = _bank(fake_bucket)
    store = _Store()
    bank.upsert_note(_note())
    await project.drain_index(bank, store, embedder=None)   # M2 behaviour
    assert "jira:LUZ-1" in store.rows and store.embeds == []


def test_build_embedder_gated_on_vertex_env(monkeypatch):
    monkeypatch.delenv("VERTEX_PROJECT", raising=False)
    monkeypatch.delenv("VERTEX_LOCATION", raising=False)
    assert embed.build_embedder() is None
    monkeypatch.setenv("VERTEX_PROJECT", "p")
    monkeypatch.setenv("VERTEX_LOCATION", "us-central1")
    assert callable(embed.build_embedder())     # callable, but not invoked (would need vertexai)


async def test_drain_batches_embed_calls(fake_bucket, monkeypatch):
    monkeypatch.setenv("MEMORY_BACKEND", "hybrid")
    bank = _bank(fake_bucket)
    for i in (1, 2, 3):
        bank.upsert_note(Note(id=f"jira:LUZ-{i}", type="jira-issue", title=f"n{i}", synopsis=f"s{i}"))
    store = _Store()
    calls: list[int] = []

    async def _batch(texts):
        calls.append(len(texts))
        return [[0.1, 0.2, 0.3] for _ in texts]

    await project.drain_index(bank, store, embedder=_batch)
    assert calls == [3]                   # ONE Vertex call for all 3 nodes (not 3 calls)
    assert len(store.embeds) == 3         # each node still embedded


async def test_drain_embed_batch_size_splits_calls(fake_bucket, monkeypatch):
    monkeypatch.setenv("MEMORY_BACKEND", "hybrid")
    bank = _bank(fake_bucket)
    for i in range(5):
        bank.upsert_note(Note(id=f"jira:LUZ-{i}", type="jira-issue", title=f"n{i}", synopsis=f"s{i}"))
    store = _Store()
    calls: list[int] = []

    async def _batch(texts):
        calls.append(len(texts))
        return [[0.1, 0.2, 0.3] for _ in texts]

    await project.drain_index(bank, store, embedder=_batch, embed_batch=2)
    assert calls == [2, 2, 1]             # 5 nodes at batch=2 → three calls, tail flush of 1
    assert len(store.embeds) == 5
