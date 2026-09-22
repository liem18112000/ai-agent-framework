"""InMemoryVectorStore — offline unit tests for the pure-Python VectorStore adapter (no DB, no network).

Deterministic: hand-made embedding vectors, no randomness. Also asserts the ports-and-adapters
contract — both the in-memory and the pgvector class satisfy the `@runtime_checkable` VectorStore
Protocol — and that the factory selects the in-memory backend from env.
"""

from __future__ import annotations

import pytest

from common.memory.pg import PgMemoryStore
from common.memory.vector_factory import build_vector_store
from common.memory.vector_memory import InMemoryVectorStore
from common.memory.vector_store import VectorStore


def _node(nid: str, **kw) -> dict:
    row = {
        "id": nid, "type": "jira-issue", "kind": "", "title": "", "synopsis": "",
        "source_url": "", "content_uri": "", "run_id": "", "context_id": "",
        "scope": "context", "status": "active", "confidence": "high", "meta": {},
    }
    row.update(kw)
    return row


# --- ports-and-adapters contract ------------------------------------------ #

def test_both_adapters_satisfy_the_protocol():
    assert isinstance(InMemoryVectorStore(), VectorStore)
    assert isinstance(PgMemoryStore(None), VectorStore)      # duck-typed; ctor never touches the DB
    assert not isinstance(object(), VectorStore)             # a non-conforming object is rejected


def test_factory_selects_in_memory_backend(monkeypatch):
    monkeypatch.setenv("VECTOR_BACKEND", "memory")
    store = build_vector_store()
    assert isinstance(store, InMemoryVectorStore)


def test_factory_rejects_unknown_backend(monkeypatch):
    monkeypatch.setenv("VECTOR_BACKEND", "nope")
    with pytest.raises(ValueError, match="nope"):
        build_vector_store()


# --- hybrid search -------------------------------------------------------- #

async def test_search_vector_ranks_nearest():
    store = InMemoryVectorStore()
    embeds = {"a": [1.0, 0.0, 0.0], "b": [0.0, 1.0, 0.0], "c": [0.0, 0.0, 1.0]}
    for nid, vec in embeds.items():
        await store.upsert_node(_node(nid, title=f"node {nid}", synopsis=f"syn {nid}"))
        await store.set_embedding(nid, vec)
    rows = await store.search(q_embed=[0.9, 0.1, 0.0], k=3)          # closest to "a"
    assert rows[0]["id"] == "a"
    assert set(rows[0]) == {"id", "type", "title"}                    # pg-shape result rows


async def test_search_lexical_matches_and_excludes_non_matches():
    store = InMemoryVectorStore()
    await store.upsert_node(_node("a", title="dunning reminder", synopsis="credit card"))
    await store.upsert_node(_node("b", title="health archive", synopsis="zip import"))
    ids = {r["id"] for r in await store.search(q_text="dunning", k=5)}
    assert ids == {"a"}                                              # only the tsv-matching node


async def test_search_hybrid_fuses_both_arms():
    store = InMemoryVectorStore()
    await store.upsert_node(_node("a", title="dunning reminder", synopsis="x"))
    await store.set_embedding("a", [1.0, 0.0])
    await store.upsert_node(_node("b", title="payment schedule", synopsis="y"))
    await store.set_embedding("b", [0.0, 1.0])
    rows = await store.search(q_text="dunning", q_embed=[0.0, 1.0], k=5)  # lexical→a, vector→b
    assert {r["id"] for r in rows} == {"a", "b"}                          # RRF union of both arms


async def test_search_type_and_scope_filter():
    store = InMemoryVectorStore()
    await store.upsert_node(_node("keep", title="dunning", type="jira-issue", scope="context"))
    await store.upsert_node(_node("drop_type", title="dunning", type="confluence-page"))
    await store.upsert_node(_node("drop_scope", title="dunning", scope="run"))
    ids = {r["id"] for r in await store.search(q_text="dunning", types=["jira-issue"], k=5)}
    assert ids == {"keep"}                                           # type + default-scope filtered


async def test_search_empty_query_returns_recent():
    store = InMemoryVectorStore()
    await store.upsert_node(_node("old", title="first"))
    await store.upsert_node(_node("new", title="second"))
    rows = await store.search(k=5)                                   # no query → created_at DESC
    assert [r["id"] for r in rows] == ["new", "old"]


async def test_search_nonmatching_real_query_returns_empty_not_recent():
    # MEM-03: a real query that matches nothing must NOT fall back to recent nodes (false positive);
    # only the empty-query browse case returns recent.
    store = InMemoryVectorStore()
    await store.upsert_node(_node("a", title="dunning reminder", synopsis="credit card"))
    await store.upsert_node(_node("b", title="health archive", synopsis="zip import"))
    assert await store.search(q_text="nonexistent-xyz", k=5) == []   # no lex/vec hit → []
    assert {r["id"] for r in await store.search(k=5)} == {"a", "b"}   # empty query still browses recent


# --- embedding freshness -------------------------------------------------- #

async def test_embedding_freshness_tracks_hash():
    store = InMemoryVectorStore()
    await store.upsert_node(_node("n1", synopsis="s"))
    await store.set_embedding("n1", [0.0, 1.0], emb_hash="h1")
    assert await store.embedding_fresh("n1", "h1") is True
    assert await store.embedding_fresh("n1", "other") is False
    assert await store.embedding_fresh("missing", "h1") is False


async def test_meta_merge_preserves_emb_hash_across_upsert():
    store = InMemoryVectorStore()
    await store.upsert_node(_node("n1", title="t", synopsis="s"))
    await store.set_embedding("n1", [0.0, 1.0], emb_hash="h1")
    await store.upsert_node(_node("n1", title="t2", synopsis="s2", meta={"x": 1}))  # re-project
    assert await store.embedding_fresh("n1", "h1") is True


# --- grounding gate ------------------------------------------------------- #

async def test_grounded_edge_gate():
    store = InMemoryVectorStore()
    await store.upsert_node(_node("cand"))
    await store.upsert_edges([{"source_id": "cand", "target": "anchor",
                               "type": "x", "origin": "y", "in_scope": True}])
    assert await store.grounded("cand", {"anchor"}) is True         # shares an edge
    assert await store.grounded("cand", {"other"}) is False         # no shared edge
    assert await store.grounded("cand", set()) is True              # no anchors → vacuously grounded
    assert await store.grounded("anchor", {"anchor"}) is True       # candidate IS an anchor


# --- prior-lesson recall (structural ∪ semantic) -------------------------- #

async def test_recall_structural_then_semantic():
    store = InMemoryVectorStore()
    # structural: a lesson edged to the run's seed ref
    await store.upsert_node(_node("insight:l1", type="insight", kind="lesson", synopsis="grounded lesson"))
    await store.upsert_edges([{"source_id": "insight:l1", "target": "jira:S",
                               "type": "insight", "origin": "lesson", "in_scope": True}])
    assert "grounded lesson" in await store.recall(seed_refs={"jira:S"})

    # semantic: a shared lesson reached by vector nearness (no edge)
    await store.upsert_node(_node("insight:l2", type="insight", kind="lesson",
                                  synopsis="shared lesson", scope="shared"))
    await store.set_embedding("insight:l2", [0.0, 0.0, 1.0])
    assert "shared lesson" in await store.recall(seed_refs=set(), q_embed=[0.0, 0.0, 1.0])


async def test_recall_high_confidence_first():
    store = InMemoryVectorStore()
    await store.upsert_node(_node("insight:lo", type="insight", kind="lesson",
                                  synopsis="low one", confidence="low"))
    await store.upsert_node(_node("insight:hi", type="insight", kind="lesson",
                                  synopsis="high one", confidence="high"))
    for nid in ("insight:lo", "insight:hi"):
        await store.upsert_edges([{"source_id": nid, "target": "jira:S",
                                   "type": "insight", "origin": "lesson", "in_scope": True}])
    assert await store.recall(seed_refs={"jira:S"}) == ["high one", "low one"]


async def test_recall_respects_limit():
    store = InMemoryVectorStore()
    for i in range(4):
        nid = f"insight:l{i}"
        await store.upsert_node(_node(nid, type="insight", kind="lesson", synopsis=f"lesson {i}"))
        await store.upsert_edges([{"source_id": nid, "target": "jira:S",
                                   "type": "insight", "origin": "lesson", "in_scope": True}])
    assert len(await store.recall(seed_refs={"jira:S"}, limit=2)) == 2


async def test_ensure_ann_index_is_a_noop():
    store = InMemoryVectorStore()
    assert await store.ensure_ann_index() is None
