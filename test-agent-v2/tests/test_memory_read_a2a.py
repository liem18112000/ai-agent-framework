"""The `search-memory` and `get-note` read skills, driven through the real A2A stack."""

from __future__ import annotations

import json

from conftest import FakeBucket
from starlette.testclient import TestClient
from test_refine_a2a import _app, _send

from common.memory import MemoryBank
from common.models import Note


def _seeded_bucket() -> FakeBucket:
    """A bucket holding one distilled note ('jira:LUZ-1') and its index node."""
    b = FakeBucket()
    bank = MemoryBank(b)
    note = Note(id="jira:LUZ-1", type="jira-issue", title="Login bug",
                synopsis="Users cannot log in.", source_url="http://x/LUZ-1")
    bank.upsert_note(note)
    bank.update_index(lambda g: g.add_note(note))
    return b


def test_search_memory_lists_matching_nodes():
    c = TestClient(_app(bucket=_seeded_bucket()))
    s = json.dumps(_send(c, "search-memory login", context_id="ctx-s"))
    assert "jira:LUZ-1" in s and "jira-issue" in s


def test_search_memory_no_match():
    c = TestClient(_app(bucket=_seeded_bucket()))
    s = json.dumps(_send(c, "search-memory zzznope", context_id="ctx-s2"))
    assert "No memory nodes match" in s


def test_search_memory_empty_query_summarizes_index():
    c = TestClient(_app(bucket=_seeded_bucket()))
    s = json.dumps(_send(c, "search-memory", context_id="ctx-s3"))
    assert "node(s)" in s and "jira:LUZ-1" in s


def test_get_note_returns_the_note():
    c = TestClient(_app(bucket=_seeded_bucket()))
    s = json.dumps(_send(c, "get-note jira:LUZ-1", context_id="ctx-n"))
    assert "No note" not in s
    assert "jira:LUZ-1" in s and "Login bug" in s


def test_get_note_unknown_id_is_helpful():
    c = TestClient(_app(bucket=_seeded_bucket()))
    s = json.dumps(_send(c, "get-note jira:NOPE", context_id="ctx-n2"))
    assert "No note" in s and "search-memory" in s


def test_get_note_requires_an_id():
    c = TestClient(_app(bucket=_seeded_bucket()))
    s = json.dumps(_send(c, "get-note", context_id="ctx-n3"))
    assert "Provide a note id" in s
