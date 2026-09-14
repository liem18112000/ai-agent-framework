"""M2 tests: GCS memory bank — note upsert/merge, index CAS, run-log."""

from __future__ import annotations

import json

import pytest

from common.interrogate.pack import load_pack
from common.memory import INDEX_JSON, MemoryBank
from common.memory.serialize import note_from_dict
from common.models import INSIGHT, LinkRecord, Note, RunLog
from common.store import CASConflict


class FakeBlob:
    def __init__(self, bucket, name):
        self._bucket, self.name = bucket, name

    @property
    def generation(self):
        return self._bucket.gens.get(self.name, 0)

    def download_as_text(self):
        return self._bucket.store[self.name]

    def upload_from_string(self, data, content_type=None, if_generation_match=None):
        current = self._bucket.gens.get(self.name, 0)
        if if_generation_match is not None and if_generation_match != current:
            raise CASConflict("generation mismatch")
        self._bucket.store[self.name] = data
        self._bucket.gens[self.name] = current + 1


class FakeBucket:
    def __init__(self):
        self.store: dict[str, str] = {}
        self.gens: dict[str, int] = {}

    def blob(self, name):
        return FakeBlob(self, name)

    def get_blob(self, name):
        return FakeBlob(self, name) if name in self.store else None


def _note(canon="jira:LUZ-158390", links=None, run_id=""):
    return Note(
        id=canon,
        type="jira-issue",
        title="[eArchive] Import",
        synopsis="synopsis",
        run_id=run_id,
        links=links or [LinkRecord(
            "jira:LUZ-158390",
            "https://axonivy.atlassian.net/wiki/spaces/LUZ/pages/49662787598/Perf",
            "confluence-page", "description",
            canonical_url="confluence:49662787598", in_scope=True)],
    )


def test_note_roundtrip_and_md():
    bank = MemoryBank(FakeBucket())
    path = bank.upsert_note(_note())
    assert path == "memory/notes/jira-issue/jira_LUZ-158390.md"
    got = bank.read_note("jira:LUZ-158390", "jira-issue")
    assert got is not None and got.title == "[eArchive] Import"
    assert got.links[0].canonical_url == "confluence:49662787598"
    md = bank._bucket.store[bank._note_md("jira-issue", "jira:LUZ-158390")]
    assert "## Links" in md and "49662787598" in md


def test_long_url_note_id_stays_under_gcs_key_limit():
    # Regression: an external-web note whose id is a very long URL used to build a GCS object
    # key over the 1024-char limit → 400 → the whole gather aborted. _slug now caps + hashes.
    from common.memory.bank import _SLUG_MAX, _slug

    long_id = "https://sequencediagram.org/index.html?initialData=" + "C4" * 700
    assert len(_slug(long_id)) <= _SLUG_MAX
    assert _slug(long_id) == _slug(long_id)  # deterministic (json/md pair + read must match)
    assert _slug(long_id) != _slug(long_id + "x")  # distinct long ids stay distinct
    assert _slug("jira:LUZ-158390") == "jira_LUZ-158390"  # short ids unchanged

    bank = MemoryBank(FakeBucket())
    path = bank.upsert_note(_note(canon=long_id))
    assert len(path) < 1024
    assert bank.read_note(long_id, "jira-issue") is not None  # round-trips through the capped key


def test_note_upsert_merges_links():
    bank = MemoryBank(FakeBucket())
    bank.upsert_note(_note())
    extra = LinkRecord("jira:LUZ-158390", "u2", "bitbucket", "description",
                       canonical_url="https://bitbucket.org/x", in_scope=False)
    bank.upsert_note(_note(links=[extra]))
    got = bank.read_note("jira:LUZ-158390", "jira-issue")
    canons = {lr.canonical_url for lr in got.links}
    assert canons == {"confluence:49662787598", "https://bitbucket.org/x"}


def test_index_cas_roundtrip():
    bank = MemoryBank(FakeBucket())
    bank.update_index(lambda g: g.add_note(_note()))
    graph, gen = bank.load_index()
    assert "jira:LUZ-158390" in graph.nodes
    assert gen == 1
    data = json.loads(bank._bucket.store[INDEX_JSON])
    assert data["edges"][0]["target"] == "confluence:49662787598"


def test_index_cas_retries_on_concurrent_write():
    bucket = FakeBucket()
    bank = MemoryBank(bucket)
    bank.update_index(lambda g: g.add_note(_note("jira:A")))

    calls = {"n": 0}

    def mutate(g):
        if calls["n"] == 0:
            bucket.gens[INDEX_JSON] += 1
        calls["n"] += 1
        g.add_note(_note("jira:B"))

    bank.update_index(mutate)
    assert calls["n"] == 2
    graph, _ = bank.load_index()
    assert "jira:B" in graph.nodes


def test_run_log_and_redactor():
    bank = MemoryBank(FakeBucket(), redactor=lambda s: s.replace("SECRET", "<redacted>"))
    run = RunLog(run_id="6f2a", seed="LUZ-158390", started="2026-08-27T09-40-00Z",
                 sources=["jira:LUZ-158390 SECRET"], nodes_fetched=3, links_found=8)
    path = bank.append_run_log(run)
    assert path == "memory/runs/2026-08-27T09-40-00Z_run-6f2a.md"
    body = bank._bucket.store[path]
    assert "SECRET" not in body and "<redacted>" in body


def test_read_missing_note_returns_none():
    assert MemoryBank(FakeBucket()).read_note("jira:NOPE", "jira-issue") is None


def test_load_pack_skips_insight_nodes():
    """A cold load_pack over the shared index must skip INSIGHT nodes: their JSON sidecar"""
    bank = MemoryBank(FakeBucket())
    bank.upsert_note(_note(run_id="run-990d"))
    bank.update_index(lambda g: g.add_note(_note()))

    insight_id = "insight:run-990d:Q-bus-001"
    insight_json = {
        "id": insight_id, "kind": "assumption", "context_id": "run-990d",
        "question_id": "Q-bus-001", "statement": "Self-answered ...", "answered_by": "agent-self",
        "confidence": "low", "source_refs": ["jira:LUZ-158392"], "rejected": [],
    }
    bank._bucket.blob(bank._note_json(INSIGHT, insight_id)).upload_from_string(
        json.dumps(insight_json), content_type="application/json")
    bank.update_index(
        lambda g: g.nodes.__setitem__(insight_id, {"id": insight_id, "type": INSIGHT, "title": "Q"})
    )

    pack = load_pack(bank, "run-990d")
    ids = {n.id for n in pack.notes}
    assert "jira:LUZ-158390" in ids
    assert insight_id not in ids


def test_load_pack_scopes_to_own_context_run():
    """B0 de-bias: the shared index merges every run's nodes, but load_pack must return ONLY the"""
    bank = MemoryBank(FakeBucket())
    mine = _note("jira:LUZ-159312", run_id="run-mine")
    other = _note("jira:LUZ-158390", run_id="run-other")
    for n in (mine, other):
        bank.upsert_note(n)
        bank.update_index(lambda g, n=n: g.add_note(n))

    ids = {n.id for n in load_pack(bank, "run-mine").notes}
    assert ids == {"jira:LUZ-159312"}
    assert load_pack(bank, "run-nomatch").notes == []


def test_note_from_dict_tolerates_unknown_keys():
    """note_from_dict drops unknown keys (schema-drift tolerant) so a stray field can't crash it."""
    note = note_from_dict(
        {"id": "jira:X", "type": "jira-issue", "kind": "assumption", "bogus": 1, "links": []}
    )
    assert note.id == "jira:X" and note.type == "jira-issue"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
