"""M1: the retrieval facade dispatches on MEMORY_BACKEND and falls back to the GCS graph."""

from __future__ import annotations

import pytest

from common.memory import retrieve
from common.models import Graph


class _FakeBank:
    def __init__(self, graph: Graph):
        self._graph = graph

    def load_index(self):
        return self._graph, 0


class _FakeStore:
    def __init__(self, rows=None, boom=False):
        self._rows, self._boom = rows or [], boom

    async def search(self, *, q_text, q_embed=None):
        if self._boom:
            raise RuntimeError("db down")
        return self._rows


def _bank(*nodes):
    g = Graph()
    for n in nodes:
        g.nodes[n["id"]] = n
    return _FakeBank(g)


_LOGIN = {"id": "jira:LUZ-1", "type": "jira-issue", "title": "Login"}


@pytest.fixture(autouse=True)
def _clean_backend(monkeypatch):
    monkeypatch.delenv("MEMORY_BACKEND", raising=False)
    yield


async def test_default_backend_uses_graph():
    nodes = await retrieve.search_nodes(_bank(_LOGIN), "login")
    assert {n["id"] for n in nodes} == {"jira:LUZ-1"}


async def test_store_none_ignores_backend(monkeypatch):
    monkeypatch.setenv("MEMORY_BACKEND", "postgres")           # no store → still the graph
    nodes = await retrieve.search_nodes(_bank(_LOGIN), "login", store=None)
    assert {n["id"] for n in nodes} == {"jira:LUZ-1"}


async def test_hybrid_prefers_store(monkeypatch):
    monkeypatch.setenv("MEMORY_BACKEND", "hybrid")
    store = _FakeStore(rows=[{"id": "pg:1", "type": "jira-issue", "title": "Hit"}])
    nodes = await retrieve.search_nodes(_bank(_LOGIN), "anything", store=store)
    assert {n["id"] for n in nodes} == {"pg:1"}


async def test_hybrid_falls_back_on_store_error(monkeypatch):
    monkeypatch.setenv("MEMORY_BACKEND", "hybrid")
    nodes = await retrieve.search_nodes(_bank(_LOGIN), "login", store=_FakeStore(boom=True))
    assert {n["id"] for n in nodes} == {"jira:LUZ-1"}          # graph fallback


async def test_hybrid_empty_store_falls_back(monkeypatch):
    monkeypatch.setenv("MEMORY_BACKEND", "hybrid")             # hybrid: empty PG → try the graph
    nodes = await retrieve.search_nodes(_bank(_LOGIN), "login", store=_FakeStore(rows=[]))
    assert {n["id"] for n in nodes} == {"jira:LUZ-1"}


async def test_postgres_empty_is_authoritative(monkeypatch):
    monkeypatch.setenv("MEMORY_BACKEND", "postgres")           # postgres: empty PG is the answer
    nodes = await retrieve.search_nodes(_bank(_LOGIN), "login", store=_FakeStore(rows=[]))
    assert nodes == []
