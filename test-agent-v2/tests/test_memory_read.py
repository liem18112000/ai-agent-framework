"""The search_memory / get_note ADK read tools over a seeded memory bank (was the A2A read skills)."""

from __future__ import annotations

import pytest

from common.adk import tools
from common.memory import MemoryBank
from common.models import Note
from tests.conftest import FakeBucket


@pytest.fixture
def seeded(monkeypatch) -> MemoryBank:
    """A bank holding one distilled note ('jira:LUZ-1') + its index node, wired into the read tools."""
    bank = MemoryBank(FakeBucket())
    note = Note(id="jira:LUZ-1", type="jira-issue", title="Login bug",
                synopsis="Users cannot log in.", source_url="http://x/LUZ-1")
    bank.upsert_note(note)
    bank.update_index(lambda g: g.add_note(note))
    monkeypatch.setattr(tools, "build_bank", lambda: bank)
    return bank


async def test_search_memory_lists_matching_nodes(seeded):
    out = await tools.search_memory("login")
    assert "jira:LUZ-1" in out and "jira-issue" in out


async def test_search_memory_no_match(seeded):
    assert "No matching nodes" in await tools.search_memory("zzznope")


async def test_search_memory_empty_query_lists_index(seeded):
    assert "jira:LUZ-1" in await tools.search_memory("")


async def test_get_note_returns_the_note(seeded):
    out = await tools.get_note("jira:LUZ-1")
    assert "No note" not in out and "Login bug" in out


async def test_get_note_resolves_by_index_not_search(seeded, monkeypatch):
    """MEM-01: get_note finds a note by exact id via the graph index even when semantic search
    would miss it (the pg top-k bug — the id 'jira:LUZ-1' is absent from title/synopsis)."""
    async def _search_misses(*a, **k):  # simulate a corpus > top-k: the node isn't returned
        return []
    monkeypatch.setattr(tools.retrieve, "search_nodes", _search_misses)
    out = await tools.get_note("jira:LUZ-1")
    assert "No note" not in out and "Login bug" in out


async def test_get_note_unknown_id_is_helpful(seeded):
    assert "No note found" in await tools.get_note("jira:NOPE")


async def test_get_note_missing_id_is_helpful(seeded):
    assert "No note found" in await tools.get_note("")
