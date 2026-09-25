"""M4b: the recall facade dispatches to the pg store (structural ∪ semantic) or the GCS graph."""

from __future__ import annotations

import common.learn as learn_pkg
from common.memory import retrieve


class _FakeStore:
    def __init__(self, hits):
        self._hits = hits
        self.seen_embed = "unset"
        self.seen_steps = "unset"

    async def recall(self, *, seed_refs, q_embed=None, limit=5, steps=()):
        self.seen_embed = q_embed
        self.seen_steps = steps
        return self._hits


def _use_store(monkeypatch, store):
    monkeypatch.setattr(retrieve, "_build_store", lambda: store)


def _graph_returns(monkeypatch, value):
    monkeypatch.setattr(learn_pkg, "recall_lessons", lambda bank, **kw: value)


async def test_gcs_uses_graph_recall(monkeypatch):
    monkeypatch.delenv("MEMORY_BACKEND", raising=False)
    _graph_returns(monkeypatch, ["graph-lesson"])
    _use_store(monkeypatch, _FakeStore(["should-not-be-used"]))
    monkeypatch.setattr(retrieve, "_build_store", lambda: (_ for _ in ()).throw(AssertionError("built")))
    out = await retrieve.recall_lessons(None, seed_refs={"jira:LUZ-1"})
    assert out == ["graph-lesson"]


async def test_postgres_uses_store(monkeypatch):
    monkeypatch.setenv("MEMORY_BACKEND", "postgres")
    _use_store(monkeypatch, _FakeStore(["pg-lesson"]))
    out = await retrieve.recall_lessons(None, seed_refs={"jira:LUZ-1"})
    assert out == ["pg-lesson"]


async def test_hybrid_empty_store_falls_back_to_graph(monkeypatch):
    monkeypatch.setenv("MEMORY_BACKEND", "hybrid")
    _use_store(monkeypatch, _FakeStore([]))
    _graph_returns(monkeypatch, ["graph-lesson"])
    out = await retrieve.recall_lessons(None, seed_refs={"jira:LUZ-1"})
    assert out == ["graph-lesson"]


async def test_store_error_falls_back_to_graph(monkeypatch):
    monkeypatch.setenv("MEMORY_BACKEND", "postgres")

    class _Boom:
        async def recall(self, **kw):
            raise RuntimeError("db down")

    _use_store(monkeypatch, _Boom())
    _graph_returns(monkeypatch, ["graph-lesson"])
    out = await retrieve.recall_lessons(None, seed_refs={"jira:LUZ-1"})
    assert out == ["graph-lesson"]


async def test_query_text_is_embedded_for_the_semantic_arm(monkeypatch):
    monkeypatch.setenv("MEMORY_BACKEND", "postgres")
    from common.memory.pg import embed

    monkeypatch.setattr(embed, "embed_configured", lambda: True)

    async def _fake_q(text):
        return [0.5, 0.5]

    monkeypatch.setattr(embed, "aembed_query", _fake_q)
    store = _FakeStore(["pg-lesson"])
    _use_store(monkeypatch, store)
    out = await retrieve.recall_lessons(None, seed_refs={"jira:LUZ-1"}, query_text="dunning reminder")
    assert out == ["pg-lesson"]
    assert store.seen_embed == [0.5, 0.5]
