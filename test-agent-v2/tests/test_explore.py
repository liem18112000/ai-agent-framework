"""G5 self-exploration controller — `run_explore_loop` mechanics + the `run_gather` flag gate."""

from __future__ import annotations

import types

from google.api_core.exceptions import PreconditionFailed

from common.memory import MemoryBank
from common.models import Note
from knowledge_gathering.executor import gather as gather_mod
from knowledge_gathering.executor.gather import SeedProbe
from knowledge_gathering.explore import loop as explore_mod
from knowledge_gathering.loop import CrawlResult


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
            raise PreconditionFailed("gen")
        self._b.store[self.name] = data
        self._b.gens[self.name] = cur + 1


class _Bucket:
    def __init__(self):
        self.store, self.gens = {}, {}

    def blob(self, n):
        return _Blob(self, n)

    def get_blob(self, n):
        return _Blob(self, n) if n in self.store else None


class _Ctx:
    context_id = "run-ctx"


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


def _note(nid: str, title: str = "") -> Note:
    return Note(id=nid, type="jira-issue", title=title)


def _probe(thin: bool = True, title: str = "Export fails", terms: str = "export folders") -> SeedProbe:
    return SeedProbe(terms=terms, thin=thin, project="LUZ", title=title,
                     description="", labels=["earchive"])


def _bank() -> MemoryBank:
    return MemoryBank(_Bucket())


async def _run_loop(bank, seed, probe, run_id, extra_seeds=None):
    return await explore_mod.run_explore_loop(
        None, None, None, seed, probe, bank=bank, client=object(),
        extra_seeds=extra_seeds or [], depth=1, scope=None, distiller=None, run_id=run_id)


async def test_multi_round_then_converges(monkeypatch):
    bank = _bank()
    seeds_plan = [["jira:LUZ-2"], ["jira:LUZ-3"], []]
    notes_plan = [
        [_note("jira:LUZ-158390", "Export bug"), _note("jira:LUZ-2", "Bulk export")],
        [_note("jira:LUZ-3", "Restricted folders")],
    ]
    calls = {"exp": 0, "crawl": []}

    async def fake_exp(bank_, client_, *, seed, terms, **k):
        i = calls["exp"]
        calls["exp"] += 1
        seeds = list(seeds_plan[i]) if i < len(seeds_plan) else []
        return seeds, [f"md r{i}"]

    async def fake_crawl(client_, bank_, seed, *, extra_seeds=None, **k):
        i = len(calls["crawl"])
        calls["crawl"].append((seed, list(extra_seeds or [])))
        return CrawlResult(notes=list(notes_plan[i])) if i < len(notes_plan) else CrawlResult()

    monkeypatch.setattr(explore_mod, "expansion_round", fake_exp)
    monkeypatch.setattr(explore_mod, "crawl", fake_crawl)

    result, md, expl = await _run_loop(bank, "LUZ-158390", _probe(), "run-multi")

    assert calls["exp"] == 3
    assert len(calls["crawl"]) == 2
    assert {n.id for n in result.notes} == {"jira:LUZ-158390", "jira:LUZ-2", "jira:LUZ-3"}
    assert calls["crawl"][0] == ("LUZ-158390", ["jira:LUZ-2"])
    assert calls["crawl"][1] == ("jira:LUZ-3", [])
    assert "converged" in expl and md == ["md r0", "md r1", "md r2"]


async def test_stops_at_max_rounds(monkeypatch):
    monkeypatch.setenv("KGA_EXPLORE_MAX_ROUNDS", "2")
    bank = _bank()
    n = {"i": 0}
    crawls: list[str] = []

    async def fake_exp(bank_, client_, *, seed, terms, **k):
        n["i"] += 1
        return [f"jira:LUZ-{n['i'] + 1}"], []

    async def fake_crawl(client_, bank_, seed, *, extra_seeds=None, **k):
        crawls.append(seed)
        nid = f"jira:NODE-{len(crawls)}"
        return CrawlResult(notes=[_note(nid, f"unique subsystem title {len(crawls)}")])

    monkeypatch.setattr(explore_mod, "expansion_round", fake_exp)
    monkeypatch.setattr(explore_mod, "crawl", fake_crawl)

    _result, _md, expl = await _run_loop(bank, "LUZ-1", _probe(), "run-max")

    assert len(crawls) == 2
    assert "budget/round-limit reached" in expl


async def test_resumes_from_persisted_state(monkeypatch):
    bank = _bank()
    bank.put_json(explore_mod._state_path("run-res"), {
        "round": 1, "visited": ["jira:LUZ-1"],
        "reflections": ["round 0: seeded"], "focus": "prior",
    })
    seeds_plan = [["jira:LUZ-1", "jira:LUZ-2"], []]
    calls = {"exp": 0}
    crawls: list[tuple[str, list[str]]] = []

    async def fake_exp(bank_, client_, *, seed, terms, **k):
        i = calls["exp"]
        calls["exp"] += 1
        return (list(seeds_plan[i]) if i < len(seeds_plan) else []), []

    async def fake_crawl(client_, bank_, seed, *, extra_seeds=None, **k):
        crawls.append((seed, list(extra_seeds or [])))
        return CrawlResult(notes=[_note("jira:LUZ-2", "Bulk export")])

    monkeypatch.setattr(explore_mod, "expansion_round", fake_exp)
    monkeypatch.setattr(explore_mod, "crawl", fake_crawl)

    _result, _md, expl = await _run_loop(bank, "LUZ-999", _probe(), "run-res")

    assert len(crawls) == 1
    assert crawls[0][0] == "jira:LUZ-2"
    assert all("jira:LUZ-1" != s and "jira:LUZ-1" not in extra for s, extra in crawls)
    assert "round 0: seeded" in expl and "round 1:" in expl


async def test_visited_node_not_repromoted(monkeypatch):
    bank = _bank()
    seeds_plan = [["jira:LUZ-2"], ["jira:LUZ-2"]]
    calls = {"exp": 0}
    crawls: list[str] = []

    async def fake_exp(bank_, client_, *, seed, terms, **k):
        i = calls["exp"]
        calls["exp"] += 1
        return (list(seeds_plan[i]) if i < len(seeds_plan) else []), []

    async def fake_crawl(client_, bank_, seed, *, extra_seeds=None, **k):
        crawls.append(seed)
        if seed == "LUZ-158390":
            return CrawlResult(notes=[_note("jira:LUZ-158390", "Export"), _note("jira:LUZ-2", "Bulk export")])
        return CrawlResult()

    monkeypatch.setattr(explore_mod, "expansion_round", fake_exp)
    monkeypatch.setattr(explore_mod, "crawl", fake_crawl)

    result, _md, expl = await _run_loop(bank, "LUZ-158390", _probe(), "run-dedup")

    assert crawls == ["LUZ-158390"]
    assert {n.id for n in result.notes} == {"jira:LUZ-158390", "jira:LUZ-2"}
    assert "converged" in expl


async def test_crawl_error_degrades_gracefully(monkeypatch):
    bank = _bank()

    async def fake_exp(bank_, client_, *, seed, terms, **k):
        return ["jira:LUZ-2"], ["md r0"]

    async def boom_crawl(*a, **k):
        raise RuntimeError("crawl blew up")

    monkeypatch.setattr(explore_mod, "expansion_round", fake_exp)
    monkeypatch.setattr(explore_mod, "crawl", boom_crawl)

    result, md, expl = await _run_loop(bank, "LUZ-1", _probe(), "run-boom")

    assert result.notes == []
    assert md == ["md r0"]
    assert "Exploration:" in expl


async def test_expansion_error_degrades_gracefully(monkeypatch):
    bank = _bank()

    async def boom_exp(*a, **k):
        raise RuntimeError("fan-out blew up")

    async def fake_crawl(*a, **k):
        raise AssertionError("crawl must not be reached after a fan-out error")

    monkeypatch.setattr(explore_mod, "expansion_round", boom_exp)
    monkeypatch.setattr(explore_mod, "crawl", fake_crawl)

    result, _md, expl = await _run_loop(bank, "LUZ-1", _probe(), "run-boom2")

    assert result.notes == [] and "Exploration:" in expl


async def test_flag_off_uses_single_pass(monkeypatch):
    monkeypatch.delenv("KGA_EXPLORE_LOOP", raising=False)
    spy = {"loop": False}
    seen = {}

    async def spy_loop(*a, **k):
        spy["loop"] = True
        return CrawlResult(), [], ""

    async def fake_crawl(client, bank, seed, **k):
        return CrawlResult(notes=[_note("jira:LUZ-1", "X")])

    async def fake_reply(context, event_queue, text):
        seen["reply"] = text

    monkeypatch.setattr(explore_mod, "run_explore_loop", spy_loop)
    monkeypatch.setattr(gather_mod, "crawl", fake_crawl)
    monkeypatch.setattr(gather_mod, "reply", fake_reply)

    ex = types.SimpleNamespace(_client=_IssueClient(), _bank=_bank(), _distiller=None)
    await gather_mod.run_gather(ex, _Ctx(), object(), "gather LUZ-1 depth 1")

    assert spy["loop"] is False
    assert "Gather complete" in seen["reply"]
    assert "Exploration:" not in seen["reply"]


async def test_flag_on_enters_loop(monkeypatch):
    monkeypatch.setenv("KGA_EXPLORE_LOOP", "1")
    seen = {}
    seeds_plan = [["jira:LUZ-2"], []]
    calls = {"exp": 0}
    crawls: list[str] = []

    async def fake_exp(bank_, client_, *, seed, terms, **k):
        i = calls["exp"]
        calls["exp"] += 1
        return (list(seeds_plan[i]) if i < len(seeds_plan) else []), []

    async def fake_crawl(client_, bank_, seed, *, extra_seeds=None, **k):
        crawls.append(seed)
        if seed == "LUZ-158390":
            return CrawlResult(notes=[_note("jira:LUZ-158390", "Export"), _note("jira:LUZ-2", "Bulk export")])
        return CrawlResult()

    async def fake_reply(context, event_queue, text):
        seen["reply"] = text

    monkeypatch.setattr(explore_mod, "expansion_round", fake_exp)
    monkeypatch.setattr(explore_mod, "crawl", fake_crawl)
    monkeypatch.setattr(gather_mod, "reply", fake_reply)

    ex = types.SimpleNamespace(_client=_IssueClient(), _bank=_bank(), _distiller=None)
    await gather_mod.run_gather(ex, _Ctx(), object(), "gather LUZ-158390 depth 1")

    assert crawls == ["LUZ-158390"]
    assert "Exploration:" in seen["reply"] and "converged" in seen["reply"]
    assert "2 nodes" in seen["reply"]


async def test_thin_seed_climbs_to_parent_and_skips_memory_recall(monkeypatch):
    """B1: a thin container with a parent promotes the parent (real AC) and does NOT fall into"""
    from knowledge_gathering.explore import expand as expand_mod

    recalls: list[str] = []
    monkeypatch.setattr(expand_mod, "memory_self_seed",
                        lambda bank, seed, focus: (recalls.append(seed) or (["jira:BLED-1"], "prior")))

    new_seeds, md = await expand_mod.expansion_round(
        _bank(), _IssueClient(), seed="LUZ-159312", terms="functional performance test",
        thin=True, project="LUZ", title="Functional Test", parent="LUZ-156281", exclude=set())

    assert "jira:LUZ-156281" in new_seeds
    assert "jira:BLED-1" not in new_seeds
    assert recalls == []
    assert any("climbed to structural parent LUZ-156281" in m for m in md)


async def test_thin_orphan_falls_back_to_memory_recall(monkeypatch):
    """A thin seed with NO parent still gets memory recall — never left blank."""
    from knowledge_gathering.explore import expand as expand_mod

    recalls: list[str] = []
    monkeypatch.setattr(expand_mod, "memory_self_seed",
                        lambda bank, seed, focus: (recalls.append(seed) or (["jira:PRIOR-1"], "prior")))

    new_seeds, _ = await expand_mod.expansion_round(
        _bank(), _IssueClient(), seed="LUZ-159312", terms="functional test",
        thin=True, project="LUZ", title="Functional Test", parent=None, exclude=set())

    assert recalls == ["LUZ-159312"]
    assert "jira:PRIOR-1" in new_seeds


async def test_non_thin_seed_does_not_climb(monkeypatch):
    """A seed with its own gravity (not thin) keeps the normal path: no climb, recall runs."""
    from knowledge_gathering.explore import expand as expand_mod

    recalls: list[str] = []
    monkeypatch.setattr(expand_mod, "memory_self_seed",
                        lambda bank, seed, focus: (recalls.append(seed) or ([], "")))

    new_seeds, md = await expand_mod.expansion_round(
        _bank(), _IssueClient(), seed="LUZ-159312", terms="functional test",
        thin=False, project="LUZ", title="Functional Test", parent="LUZ-156281", exclude=set())

    assert "jira:LUZ-156281" not in new_seeds
    assert recalls == ["LUZ-159312"]
    assert not any("climbed" in m for m in md)


async def test_codegraph_anchor_leads_every_round_focus(monkeypatch):
    """B2 Part A: once a codegraph note is attached, its code-vocabulary tokens lead every later"""
    from common.models import CODEGRAPH
    from knowledge_gathering.executor.gather import SeedProbe

    async def fake_exp(bank_, client_, *, seed, terms, **k):
        return ["jira:NEXT"], []

    seeds_seen: list[str] = []

    async def fake_crawl(client_, bank_, seed, *, extra_seeds=None, **k):
        seeds_seen.append(seed)
        if len(seeds_seen) == 1:
            return CrawlResult(notes=[
                _note("jira:LUZ-1", "thin ticket"),
                Note(id="codegraph:ws/repo", type=CODEGRAPH, title="ws/repo",
                     synopsis="PaymentController enrollment dunning endpoints"),
            ])
        return CrawlResult(notes=[_note(f"jira:R{len(seeds_seen)}", "more")])

    monkeypatch.setattr(explore_mod, "expansion_round", fake_exp)
    monkeypatch.setattr(explore_mod, "crawl", fake_crawl)
    monkeypatch.setenv("KGA_EXPLORE_MAX_ROUNDS", "3")

    probe = SeedProbe(terms="functional test", thin=True, project="LUZ", title="Functional Test")
    _r, _md, exploration_md = await _run_loop(_bank(), "LUZ-1", probe, "run-anchor")

    assert "paymentcontroller" in exploration_md.lower()


async def test_codegraph_auto_resolves_devpanel_repo_when_enabled(monkeypatch):
    """B2 Part B (opt-in): a dev-panel codegraph the seed crawl only RECORDED is auto-promoted and"""
    from common.models import CODEGRAPH, LinkRecord
    from knowledge_gathering.executor.gather import SeedProbe

    async def fake_exp(bank_, client_, *, seed, terms, **k):
        return [], []

    seeds_seen: list[str] = []

    async def fake_crawl(client_, bank_, seed, *, extra_seeds=None, **k):
        seeds_seen.append(seed)
        if seed == "codegraph:ws/repo":
            return CrawlResult(notes=[Note(id="codegraph:ws/repo", type=CODEGRAPH,
                                           title="ws/repo", synopsis="PaymentController endpoints")])
        return CrawlResult(
            notes=[_note("jira:LUZ-1", "thin ticket")],
            inventory=[LinkRecord("jira:LUZ-1", "https://bitbucket.org/ws/repo", CODEGRAPH,
                                  "devpanel", canonical_url="codegraph:ws/repo", in_scope=False)])

    monkeypatch.setattr(explore_mod, "expansion_round", fake_exp)
    monkeypatch.setattr(explore_mod, "crawl", fake_crawl)
    monkeypatch.setenv("KGA_EXPLORE_CODEGRAPH", "1")
    monkeypatch.setenv("KGA_EXPLORE_MAX_ROUNDS", "3")

    probe = SeedProbe(terms="functional test", thin=True, project="LUZ", title="Functional Test")
    await _run_loop(_bank(), "LUZ-1", probe, "run-auto")

    assert "codegraph:ws/repo" in seeds_seen


async def test_codegraph_auto_resolve_off_by_default(monkeypatch):
    """Without the flag, a recorded dev-panel codegraph is NOT auto-built (human confirms the repo)."""
    from common.models import CODEGRAPH, LinkRecord
    from knowledge_gathering.executor.gather import SeedProbe

    async def fake_exp(bank_, client_, *, seed, terms, **k):
        return [], []

    seeds_seen: list[str] = []

    async def fake_crawl(client_, bank_, seed, *, extra_seeds=None, **k):
        seeds_seen.append(seed)
        return CrawlResult(
            notes=[_note("jira:LUZ-1", "thin ticket")],
            inventory=[LinkRecord("jira:LUZ-1", "https://bitbucket.org/ws/repo", CODEGRAPH,
                                  "devpanel", canonical_url="codegraph:ws/repo", in_scope=False)])

    monkeypatch.setattr(explore_mod, "expansion_round", fake_exp)
    monkeypatch.setattr(explore_mod, "crawl", fake_crawl)
    monkeypatch.delenv("KGA_EXPLORE_CODEGRAPH", raising=False)

    probe = SeedProbe(terms="functional test", thin=True, project="LUZ", title="Functional Test")
    await _run_loop(_bank(), "LUZ-1", probe, "run-off")

    assert "codegraph:ws/repo" not in seeds_seen


async def test_off_seed_round_stops_the_loop(monkeypatch):
    """B3: round 1 discovers nodes sharing NO vocabulary with the seed's own neighborhood → the"""
    from knowledge_gathering.executor.gather import SeedProbe

    async def fake_exp(bank_, client_, *, seed, terms, **k):
        return ["jira:NEXT"], []

    crawls: list[str] = []

    async def fake_crawl(client_, bank_, seed, *, extra_seeds=None, **k):
        crawls.append(seed)
        if len(crawls) == 1:
            return CrawlResult(notes=[_note("jira:LUZ-1", "billing dunning retry schedule")])
        return CrawlResult(notes=[_note("jira:ZIP", "zipimport transfer metadata archive folders")])

    monkeypatch.setattr(explore_mod, "expansion_round", fake_exp)
    monkeypatch.setattr(explore_mod, "crawl", fake_crawl)
    monkeypatch.setenv("KGA_EXPLORE_MAX_ROUNDS", "5")

    probe = SeedProbe(terms="billing dunning retry", thin=True, project="LUZ", title="Billing")
    _r, _md, expl = await _run_loop(_bank(), "LUZ-1", probe, "run-drift")

    assert len(crawls) == 2
    assert "off-seed drift" in expl


async def test_coherence_gate_disabled_by_flag(monkeypatch):
    """KGA_EXPLORE_MIN_COHERENCE=0 turns B3 off — the off-seed round no longer stops the loop."""
    from knowledge_gathering.executor.gather import SeedProbe

    async def fake_exp(bank_, client_, *, seed, terms, **k):
        return ["jira:NEXT"], []

    crawls: list[str] = []

    async def fake_crawl(client_, bank_, seed, *, extra_seeds=None, **k):
        crawls.append(seed)
        if len(crawls) == 1:
            return CrawlResult(notes=[_note("jira:LUZ-1", "billing dunning retry schedule")])
        return CrawlResult(notes=[_note(f"jira:OFF{len(crawls)}", "zipimport transfer metadata")])

    monkeypatch.setattr(explore_mod, "expansion_round", fake_exp)
    monkeypatch.setattr(explore_mod, "crawl", fake_crawl)
    monkeypatch.setenv("KGA_EXPLORE_MAX_ROUNDS", "3")
    monkeypatch.setenv("KGA_EXPLORE_MIN_COHERENCE", "0")

    probe = SeedProbe(terms="billing dunning retry", thin=True, project="LUZ", title="Billing")
    _r, _md, expl = await _run_loop(_bank(), "LUZ-1", probe, "run-nogate")

    assert len(crawls) == 3
    assert "off-seed drift" not in expl


async def test_b5_gate_drops_ungrounded_promotions(monkeypatch):
    """B5 (opt-in): with grounding on, a round-1 promotion that does NOT connect to the seed's"""
    from knowledge_gathering.executor.gather import SeedProbe

    promos = {0: ["jira:R0"], 1: ["jira:GOOD-1", "jira:BAD-1"]}
    calls = {"i": 0}

    async def fake_exp(bank_, client_, *, seed, terms, **k):
        i = calls["i"]; calls["i"] += 1
        return list(promos.get(i, [])), []

    crawls: list[str] = []

    async def fake_crawl(client_, bank_, seed, *, extra_seeds=None, **k):
        crawls.append(seed)
        return CrawlResult(notes=[_note(f"jira:N{len(crawls)}", "seed neighborhood")])

    monkeypatch.setattr(explore_mod, "graph_grounded",
                        lambda graph, cand, anchors: "GOOD" in cand)
    monkeypatch.setattr(explore_mod, "expansion_round", fake_exp)
    monkeypatch.setattr(explore_mod, "crawl", fake_crawl)
    monkeypatch.setenv("KGA_EXPLORE_GROUND_PROMOTIONS", "1")
    monkeypatch.setenv("KGA_EXPLORE_MIN_COHERENCE", "0")
    monkeypatch.setenv("KGA_EXPLORE_MAX_ROUNDS", "3")

    probe = SeedProbe(terms="seed neighborhood", thin=True, project="LUZ", title="Seed")
    await _run_loop(_bank(), "LUZ-1", probe, "run-b5")

    assert "jira:GOOD-1" in crawls
    assert "jira:BAD-1" not in crawls


async def test_b6_exclude_prunes_rejected_cluster(monkeypatch):
    """B6: re-running with exclude='zip import' prunes matching nodes from the pack (and steers the"""
    from knowledge_gathering.executor.gather import SeedProbe

    async def fake_exp(bank_, client_, *, seed, terms, **k):
        return ["jira:NEXT"], []

    async def fake_crawl(client_, bank_, seed, *, extra_seeds=None, **k):
        return CrawlResult(notes=[
            _note("jira:BILL-1", "billing dunning retry"),
            _note("jira:ZIP-1", "zip import transfer metadata"),
        ])

    monkeypatch.setattr(explore_mod, "expansion_round", fake_exp)
    monkeypatch.setattr(explore_mod, "crawl", fake_crawl)
    monkeypatch.setenv("KGA_EXPLORE_MAX_ROUNDS", "1")

    probe = SeedProbe(terms="billing dunning", thin=True, project="LUZ", title="Billing")
    result, _md, _expl = await explore_mod.run_explore_loop(
        None, None, None, "LUZ-1", probe, bank=_bank(), client=object(),
        extra_seeds=[], depth=1, scope=None, distiller=None, run_id="run-b6", exclude="zip import")

    ids = {n.id for n in result.notes}
    assert "jira:BILL-1" in ids
    assert "jira:ZIP-1" not in ids
