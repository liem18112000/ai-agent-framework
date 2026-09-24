"""Integration tests: PgMemoryStore against a REAL pgvector Postgres."""

from __future__ import annotations

import os

import pytest
import pytest_asyncio

from common.memory.pg.schema import EMBED_DIMS

pytestmark = pytest.mark.skipif(
    not os.environ.get("PGVECTOR_TEST_URL"),
    reason="set PGVECTOR_TEST_URL to a pgvector Postgres to run the pg integration tests",
)


def _vec(i: int) -> list[float]:
    """A unit vector with a single 1.0 at position i — orthogonal for different i, so cosine"""
    v = [0.0] * EMBED_DIMS
    v[i % EMBED_DIMS] = 1.0
    return v


def _node(nid: str, **kw) -> dict:
    row = {
        "id": nid, "type": "jira-issue", "kind": "", "title": "", "synopsis": "",
        "source_url": "", "content_uri": "", "run_id": "", "context_id": "",
        "scope": "context", "status": "active", "confidence": "high", "meta": {},
    }
    row.update(kw)
    return row


@pytest_asyncio.fixture
async def store():
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from common.memory.pg import PgMemoryStore

    engine = create_async_engine(os.environ["PGVECTOR_TEST_URL"])
    st = PgMemoryStore(engine)
    await st._ensure()
    async with engine.begin() as c:
        await c.execute(text("TRUNCATE memory_node, memory_edge"))
    try:
        yield st
    finally:
        await engine.dispose()


async def test_set_embedding_and_freshness(store):
    await store.upsert_node(_node("n1", synopsis="s"))
    await store.set_embedding("n1", _vec(1), emb_hash="h1")
    assert await store.embedding_fresh("n1", "h1") is True
    assert await store.embedding_fresh("n1", "other") is False


async def test_meta_merge_preserves_emb_hash(store):
    await store.upsert_node(_node("n1", title="t", synopsis="s"))
    await store.set_embedding("n1", _vec(1), emb_hash="h1")
    await store.upsert_node(_node("n1", title="t2", synopsis="s2", meta={"x": 1}))
    assert await store.embedding_fresh("n1", "h1") is True


async def test_hybrid_search_vector_ranks_nearest(store):
    for i, nid in [(1, "a"), (2, "b"), (3, "c")]:
        await store.upsert_node(_node(nid, title=f"node {nid}", synopsis=f"syn {nid}"))
        await store.set_embedding(nid, _vec(i))
    rows = await store.search(q_text="", q_embed=_vec(2), k=3)
    assert rows and rows[0]["id"] == "b"


async def test_lexical_search_matches_tsvector(store):
    await store.upsert_node(_node("a", title="dunning reminder", synopsis="credit card"))
    await store.upsert_node(_node("b", title="health archive", synopsis="zip import"))
    ids = {r["id"] for r in await store.search(q_text="dunning", k=5)}
    assert "a" in ids and "b" not in ids


async def test_grounded_edge_gate(store):
    await store.upsert_node(_node("cand"))
    await store.upsert_edges([{"source_id": "cand", "target": "anchor",
                               "type": "x", "origin": "y", "in_scope": True}])
    assert await store.grounded("cand", {"anchor"}) is True
    assert await store.grounded("cand", {"other"}) is False
    assert await store.grounded("cand", set()) is True


async def test_recall_structural_then_semantic(store):
    await store.upsert_node(_node("insight:l1", type="insight", kind="lesson", synopsis="grounded lesson"))
    await store.upsert_edges([{"source_id": "insight:l1", "target": "jira:S",
                               "type": "insight", "origin": "lesson", "in_scope": True}])
    assert "grounded lesson" in await store.recall(seed_refs={"jira:S"})

    await store.upsert_node(_node("insight:l2", type="insight", kind="lesson",
                                  synopsis="shared lesson", scope="shared"))
    await store.set_embedding("insight:l2", _vec(5))
    assert "shared lesson" in await store.recall(seed_refs=set(), q_embed=_vec(5))


async def test_recall_semantic_reaches_a_captured_context_scoped_lesson(store):
    """R0 regression, pg arm — the mirror of the InMemoryVectorStore case. `capture_lessons` mints
    every auto-captured lesson at scope="context"; the semantic leg used to filter scope='shared',
    which nothing in src/ ever writes, so the vector arm could never return a captured lesson."""
    await store.upsert_node(_node("insight:cap", type="insight", kind="lesson",
                                  synopsis="captured lesson", scope="context"))
    await store.set_embedding("insight:cap", _vec(7))
    assert "captured lesson" in await store.recall(seed_refs=set(), q_embed=_vec(7))


async def test_ensure_ann_index_idempotent(store):
    await store.upsert_node(_node("n1", synopsis="s"))
    await store.set_embedding("n1", _vec(1))
    await store.ensure_ann_index()
    await store.ensure_ann_index()
