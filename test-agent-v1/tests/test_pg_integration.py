"""Integration tests: PgMemoryStore against a REAL pgvector Postgres.

Gated on PGVECTOR_TEST_URL — SKIPPED in the normal offline suite (no DB), run in CI with a pgvector
service (see bitbucket-pipelines.yml) or locally against a throwaway container:

    docker run -d --rm -e POSTGRES_PASSWORD=pg -p 5432:5432 pgvector/pgvector:pg16
    PGVECTOR_TEST_URL=postgresql+asyncpg://postgres:pg@localhost:5432/postgres \
        pytest test-agent/tests/test_pg_integration.py

These exercise the store's REAL SQL — the class of bug the offline fakes can't catch and that only
surfaced on a live DB during rollout: multi-statement DDL (asyncpg rejects it), the
`jsonb_build_object` param-type inference (`set_embedding`), the `meta || EXCLUDED.meta` merge that
preserves emb_hash, the vector `<=>` operator, and the HNSW DDL. Vectors are deterministic fakes
(no Vertex) so ranking is exact and CI needs no cloud creds.
"""

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
    """A unit vector with a single 1.0 at position i — orthogonal for different i, so cosine
    distance is 0 to itself and 1 to any other: exact, controllable nearest-neighbour ranking."""
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
    await st._ensure()  # regression: multi-statement SCHEMA_SQL must apply (asyncpg rejects it whole)
    async with engine.begin() as c:
        await c.execute(text("TRUNCATE memory_node, memory_edge"))
    try:
        yield st
    finally:
        await engine.dispose()


async def test_set_embedding_and_freshness(store):
    await store.upsert_node(_node("n1", synopsis="s"))
    await store.set_embedding("n1", _vec(1), emb_hash="h1")  # regression: jsonb_build_object param typing
    assert await store.embedding_fresh("n1", "h1") is True
    assert await store.embedding_fresh("n1", "other") is False


async def test_meta_merge_preserves_emb_hash(store):
    await store.upsert_node(_node("n1", title="t", synopsis="s"))
    await store.set_embedding("n1", _vec(1), emb_hash="h1")
    await store.upsert_node(_node("n1", title="t2", synopsis="s2", meta={"x": 1}))  # re-project
    assert await store.embedding_fresh("n1", "h1") is True  # meta || EXCLUDED.meta kept emb_hash


async def test_hybrid_search_vector_ranks_nearest(store):
    for i, nid in [(1, "a"), (2, "b"), (3, "c")]:
        await store.upsert_node(_node(nid, title=f"node {nid}", synopsis=f"syn {nid}"))
        await store.set_embedding(nid, _vec(i))
    rows = await store.search(q_text="", q_embed=_vec(2), k=3)  # nearest to _vec(2) is 'b'
    assert rows and rows[0]["id"] == "b"


async def test_lexical_search_matches_tsvector(store):
    await store.upsert_node(_node("a", title="dunning reminder", synopsis="credit card"))
    await store.upsert_node(_node("b", title="health archive", synopsis="zip import"))
    ids = {r["id"] for r in await store.search(q_text="dunning", k=5)}  # no embeddings → lexical arm
    assert "a" in ids and "b" not in ids


async def test_grounded_edge_gate(store):
    await store.upsert_node(_node("cand"))
    await store.upsert_edges([{"source_id": "cand", "target": "anchor",
                               "type": "x", "origin": "y", "in_scope": True}])
    assert await store.grounded("cand", {"anchor"}) is True
    assert await store.grounded("cand", {"other"}) is False
    assert await store.grounded("cand", set()) is True  # nothing to gate against


async def test_recall_structural_then_semantic(store):
    await store.upsert_node(_node("insight:l1", type="insight", kind="lesson", synopsis="grounded lesson"))
    await store.upsert_edges([{"source_id": "insight:l1", "target": "jira:S",
                               "type": "insight", "origin": "lesson", "in_scope": True}])
    assert "grounded lesson" in await store.recall(seed_refs={"jira:S"})

    await store.upsert_node(_node("insight:l2", type="insight", kind="lesson",
                                  synopsis="shared lesson", scope="shared"))
    await store.set_embedding("insight:l2", _vec(5))
    assert "shared lesson" in await store.recall(seed_refs=set(), q_embed=_vec(5))


async def test_ensure_ann_index_idempotent(store):
    await store.upsert_node(_node("n1", synopsis="s"))
    await store.set_embedding("n1", _vec(1))
    await store.ensure_ann_index()  # HNSW DDL must be valid…
    await store.ensure_ann_index()  # …and idempotent
