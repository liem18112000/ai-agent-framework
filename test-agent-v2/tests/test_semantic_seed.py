"""M4c: semantic self-seed — vector-nearest fetchable seeds, B5-grounded, opt-in + DB-gated."""

from __future__ import annotations

import common.memory.pg.embed as emb
from common.memory import pg
from common.models import Graph
from knowledge_gathering.gather.explore.seeds.self_seed import semantic_self_seed
from knowledge_gathering.gather.seed import normalize_seed


def _graph(nodes, edges):
    g = Graph()
    for n in nodes:
        g.nodes[n] = {"id": n, "type": "jira-issue", "title": n}
    for s, t in edges:
        g.edges[f"{s}->{t}"] = {"source_id": s, "target": t, "type": "x", "origin": "y", "in_scope": True}
    return g


class _Bank:
    def __init__(self, g):
        self._g = g

    def load_index(self):
        return self._g, 0


class _Store:
    def __init__(self, rows):
        self._rows = rows

    async def search(self, *, q_text, q_embed=None, types=None, scopes=None, k=40):
        return self._rows


async def _stub_query(text):
    return [0.1, 0.2, 0.3]


def _wire(monkeypatch, store):
    monkeypatch.setenv("MEMORY_SEMANTIC_SEED", "1")
    monkeypatch.setenv("MEMORY_BACKEND", "hybrid")
    monkeypatch.setattr(pg, "build_store", lambda: store)
    monkeypatch.setattr(emb, "embed_configured", lambda: True)
    monkeypatch.setattr(emb, "aembed_query", _stub_query)


async def test_promotes_only_grounded_candidates(monkeypatch):
    sid, anchor, c, d = normalize_seed("LUZ-1"), "jira:EPIC", "jira:LUZ-2", "jira:LUZ-3"
    g = _graph([sid, anchor, c, d], [(sid, anchor), (c, anchor)])
    _wire(monkeypatch, _Store([{"id": c, "type": "jira-issue", "title": "C"},
                               {"id": d, "type": "jira-issue", "title": "D"}]))
    seeds, md = await semantic_self_seed(_Bank(g), "LUZ-1", "credit card dunning")
    assert seeds == [c]
    assert c in md


async def test_cold_seed_promotes_nothing(monkeypatch):
    sid = normalize_seed("LUZ-1")
    g = _graph([sid, "jira:LUZ-2"], [])
    _wire(monkeypatch, _Store([{"id": "jira:LUZ-2", "type": "jira-issue", "title": "C"}]))
    seeds, md = await semantic_self_seed(_Bank(g), "LUZ-1", "x")
    assert seeds == [] and md == ""


async def test_excludes_self_and_already_promoted(monkeypatch):
    sid, anchor, c = normalize_seed("LUZ-1"), "jira:EPIC", "jira:LUZ-2"
    g = _graph([sid, anchor, c], [(sid, anchor), (c, anchor)])
    _wire(monkeypatch, _Store([{"id": sid, "type": "jira-issue", "title": "self"},
                               {"id": c, "type": "jira-issue", "title": "C"}]))
    seeds, _ = await semantic_self_seed(_Bank(g), "LUZ-1", "x", exclude={c})
    assert seeds == []


async def test_disabled_flag_is_noop(monkeypatch):
    monkeypatch.delenv("MEMORY_SEMANTIC_SEED", raising=False)
    monkeypatch.setenv("MEMORY_BACKEND", "hybrid")
    monkeypatch.setattr(pg, "build_store", lambda: (_ for _ in ()).throw(AssertionError("built")))
    g = _graph([normalize_seed("LUZ-1"), "jira:EPIC"], [(normalize_seed("LUZ-1"), "jira:EPIC")])
    assert await semantic_self_seed(_Bank(g), "LUZ-1", "x") == ([], "")


async def test_gcs_backend_is_noop(monkeypatch):
    monkeypatch.setenv("MEMORY_SEMANTIC_SEED", "1")
    monkeypatch.delenv("MEMORY_BACKEND", raising=False)
    monkeypatch.setattr(pg, "build_store", lambda: (_ for _ in ()).throw(AssertionError("built")))
    g = _graph([normalize_seed("LUZ-1"), "jira:EPIC"], [(normalize_seed("LUZ-1"), "jira:EPIC")])
    assert await semantic_self_seed(_Bank(g), "LUZ-1", "x") == ([], "")
