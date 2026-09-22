"""B1 thin-seed climb — `expansion_round` promotes a thin container's structural parent instead of
falling into memory recall. This is the LIVE single-pass gather path (agent.py calls expansion_round
directly); the old multi-round `run_explore_loop` was never ported to ADK and has been removed."""

from __future__ import annotations

from common.memory import MemoryBank
from common.store import CASConflict


class _Blob:
    def __init__(self, b, n):
        self._b, self.name = b, n

    @property
    def generation(self):
        return self._b.gens.get(self.name, 0)

    def download_as_text(self):
        return self._b.store[self.name]

    def upload_from_string(self, data, content_type=None, if_generation_match=None):
        cur = self._b.gens.get(self.name, 0)
        if if_generation_match is not None and if_generation_match != cur:
            raise CASConflict("gen")
        self._b.store[self.name] = data
        self._b.gens[self.name] = cur + 1


class _Bucket:
    def __init__(self):
        self.store, self.gens = {}, {}

    def blob(self, n):
        return _Blob(self, n)

    def get_blob(self, n):
        return _Blob(self, n) if n in self.store else None


class _IssueClient:
    """One thin Jira issue (short body, no links/subtasks) so `_seed_probe` yields a title."""

    def __init__(self, summary="Export fails for restricted folders", labels=("earchive",)):
        self._issue = {"fields": {
            "summary": summary,
            "description": {"type": "doc", "version": 1, "content": []},
            "issuelinks": [], "subtasks": [], "labels": list(labels), "components": [],
        }}

    async def get_issue(self, key):
        return self._issue

    async def search_jql(self, jql, *, max_results=10):
        return []

    async def search_cql(self, cql, *, limit=10):
        return []


def _bank() -> MemoryBank:
    return MemoryBank(_Bucket())


async def test_thin_seed_climbs_to_parent_and_skips_memory_recall(monkeypatch):
    """B1: a thin container with a parent promotes the parent (real AC) and does NOT fall into
    memory recall."""
    from knowledge_gathering.gather.explore import expand as expand_mod

    recalls: list[str] = []
    monkeypatch.setattr(expand_mod, "memory_self_seed",
                        lambda bank, seed, focus: (recalls.append(seed) or (["jira:BLED-1"], "prior")))

    new_seeds, md = await expand_mod.expansion_round(
        _bank(), _IssueClient(), seed="LUZ-159312", terms="functional performance test",
        thin=True, project="LUZ", parent="LUZ-156281", exclude=set())

    assert "jira:LUZ-156281" in new_seeds
    assert "jira:BLED-1" not in new_seeds
    assert recalls == []
    assert any("climbed to structural parent LUZ-156281" in m for m in md)


async def test_thin_orphan_falls_back_to_memory_recall(monkeypatch):
    """A thin seed with NO parent still gets memory recall — never left blank."""
    from knowledge_gathering.gather.explore import expand as expand_mod

    recalls: list[str] = []
    monkeypatch.setattr(expand_mod, "memory_self_seed",
                        lambda bank, seed, focus: (recalls.append(seed) or (["jira:PRIOR-1"], "prior")))

    new_seeds, _ = await expand_mod.expansion_round(
        _bank(), _IssueClient(), seed="LUZ-159312", terms="functional test",
        thin=True, project="LUZ", parent=None, exclude=set())

    assert recalls == ["LUZ-159312"]
    assert "jira:PRIOR-1" in new_seeds


async def test_parallel_wave_merges_and_dedups(monkeypatch):
    """G0/G1: the seed producers fan out in parallel; results merge in stable order and cross-source
    duplicates dedup once. Exercises the `ground_leads` 3-tuple unpack path."""
    from knowledge_gathering.gather.explore import expand as expand_mod

    monkeypatch.setattr(expand_mod, "memory_self_seed", lambda b, s, f: (["jira:A"], "prior"))

    async def _sem(*a, **k):
        return ([], "")

    async def _search(*a, **k):
        return (["jira:A", "jira:B"], "search")  # jira:A overlaps memory recall

    async def _leads(*a, **k):
        return (["jira:C"], ["unconfirmed"], "leads")  # 3-tuple

    monkeypatch.setattr(expand_mod, "semantic_self_seed", _sem)
    monkeypatch.setattr(expand_mod, "atlassian_search_seeds", _search)
    monkeypatch.setattr(expand_mod, "ground_leads", _leads)

    new_seeds, md = await expand_mod.expansion_round(
        _bank(), _IssueClient(), seed="LUZ-1", terms="t", thin=True, project="LUZ",
        parent=None, exclude=set(), leads=["lead1"])

    assert new_seeds == ["jira:A", "jira:B", "jira:C"]  # A deduped once; stable order
    assert md == ["prior", "search", "leads"]  # ordered, empty semantic md dropped


async def test_non_thin_seed_does_not_climb(monkeypatch):
    """A seed with its own gravity (not thin) keeps the normal path: no climb, recall runs."""
    from knowledge_gathering.gather.explore import expand as expand_mod

    recalls: list[str] = []
    monkeypatch.setattr(expand_mod, "memory_self_seed",
                        lambda bank, seed, focus: (recalls.append(seed) or ([], "")))

    new_seeds, md = await expand_mod.expansion_round(
        _bank(), _IssueClient(), seed="LUZ-159312", terms="functional test",
        thin=False, project="LUZ", parent="LUZ-156281", exclude=set())

    assert "jira:LUZ-156281" not in new_seeds
    assert recalls == ["LUZ-159312"]
    assert not any("climbed" in m for m in md)
