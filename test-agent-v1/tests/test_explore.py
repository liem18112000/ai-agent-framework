"""G5 self-exploration controller — `run_explore_loop` mechanics + the `run_gather` flag gate.

Fakes only (no network / LLM / GCS): a tiny in-memory GCS bucket behind a real `MemoryBank` gives
the loop-state store its real `put_json`/`get_json` round-trip, and `expansion_round` / `crawl` are
monkeypatched on the explore module to script per-round yields. Proves: default-OFF single pass is
untouched, the loop runs >1 round and converges on marginal yield, the `max_rounds` bound holds,
persisted state RESUMES (not restart), already-crawled ids are never re-promoted, and any round
error degrades to the accumulated-so-far result.
"""

from __future__ import annotations

import types

from google.api_core.exceptions import PreconditionFailed

from common.memory import MemoryBank
from common.models import Note
from knowledge_gathering.executor import gather as gather_mod
from knowledge_gathering.executor.gather import SeedProbe
from knowledge_gathering.explore import loop as explore_mod
from knowledge_gathering.loop import CrawlResult


# --- minimal in-memory GCS bucket (so MemoryBank.put_json/get_json work for loop state) --- #
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


# --- multi-round + convergence (a round adds no new seed) --- #
async def test_multi_round_then_converges(monkeypatch):
    bank = _bank()
    seeds_plan = [["jira:LUZ-2"], ["jira:LUZ-3"], []]  # round 2 surfaces nothing new → converge
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

    assert calls["exp"] == 3            # rounds 0, 1, 2 all fanned out
    assert len(calls["crawl"]) == 2     # round 2 converged pre-crawl → no third crawl
    assert {n.id for n in result.notes} == {"jira:LUZ-158390", "jira:LUZ-2", "jira:LUZ-3"}
    assert calls["crawl"][0] == ("LUZ-158390", ["jira:LUZ-2"])  # round 0 crawls seed + promoted
    assert calls["crawl"][1] == ("jira:LUZ-3", [])              # round 1 crawls only the new seed
    assert "converged" in expl and md == ["md r0", "md r1", "md r2"]


# --- max_rounds bound (always new nodes, still stops) --- #
async def test_stops_at_max_rounds(monkeypatch):
    monkeypatch.setenv("KGA_EXPLORE_MAX_ROUNDS", "2")
    bank = _bank()
    n = {"i": 0}
    crawls: list[str] = []

    async def fake_exp(bank_, client_, *, seed, terms, **k):
        n["i"] += 1
        return [f"jira:LUZ-{n['i'] + 1}"], []  # a fresh, unvisited seed every round

    async def fake_crawl(client_, bank_, seed, *, extra_seeds=None, **k):
        crawls.append(seed)
        nid = f"jira:NODE-{len(crawls)}"
        return CrawlResult(notes=[_note(nid, f"unique subsystem title {len(crawls)}")])

    monkeypatch.setattr(explore_mod, "expansion_round", fake_exp)
    monkeypatch.setattr(explore_mod, "crawl", fake_crawl)

    _result, _md, expl = await _run_loop(bank, "LUZ-1", _probe(), "run-max")

    assert len(crawls) == 2  # bounded at max_rounds even though every round yields a new node
    assert "budget/round-limit reached" in expl


# --- resume from persisted GCS state (don't restart at 0, don't re-crawl visited) --- #
async def test_resumes_from_persisted_state(monkeypatch):
    bank = _bank()
    bank.put_json(explore_mod._state_path("run-res"), {
        "round": 1, "visited": ["jira:LUZ-1"],
        "reflections": ["round 0: seeded"], "focus": "prior",
    })
    seeds_plan = [["jira:LUZ-1", "jira:LUZ-2"], []]  # LUZ-1 already visited → must be filtered out
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
    assert crawls[0][0] == "jira:LUZ-2"  # resumed at round 1 (round-0 seed crawl never ran)
    assert all("jira:LUZ-1" != s and "jira:LUZ-1" not in extra for s, extra in crawls)  # not re-crawled
    assert "round 0: seeded" in expl and "round 1:" in expl  # prior reflection kept + new one added


# --- dedup across rounds: a round-0 node re-offered later is not re-promoted/re-crawled --- #
async def test_visited_node_not_repromoted(monkeypatch):
    bank = _bank()
    seeds_plan = [["jira:LUZ-2"], ["jira:LUZ-2"]]  # round 1 re-offers the already-crawled LUZ-2
    calls = {"exp": 0}
    crawls: list[str] = []

    async def fake_exp(bank_, client_, *, seed, terms, **k):
        i = calls["exp"]
        calls["exp"] += 1
        return (list(seeds_plan[i]) if i < len(seeds_plan) else []), []

    async def fake_crawl(client_, bank_, seed, *, extra_seeds=None, **k):
        crawls.append(seed)
        if seed == "LUZ-158390":  # round 0 discovers LUZ-2
            return CrawlResult(notes=[_note("jira:LUZ-158390", "Export"), _note("jira:LUZ-2", "Bulk export")])
        return CrawlResult()

    monkeypatch.setattr(explore_mod, "expansion_round", fake_exp)
    monkeypatch.setattr(explore_mod, "crawl", fake_crawl)

    result, _md, expl = await _run_loop(bank, "LUZ-158390", _probe(), "run-dedup")

    assert crawls == ["LUZ-158390"]  # round 1's re-offered LUZ-2 was filtered → no second crawl
    assert {n.id for n in result.notes} == {"jira:LUZ-158390", "jira:LUZ-2"}
    assert "converged" in expl


# --- never break gather: a crawl error degrades to the accumulated-so-far result --- #
async def test_crawl_error_degrades_gracefully(monkeypatch):
    bank = _bank()

    async def fake_exp(bank_, client_, *, seed, terms, **k):
        return ["jira:LUZ-2"], ["md r0"]

    async def boom_crawl(*a, **k):
        raise RuntimeError("crawl blew up")

    monkeypatch.setattr(explore_mod, "expansion_round", fake_exp)
    monkeypatch.setattr(explore_mod, "crawl", boom_crawl)

    result, md, expl = await _run_loop(bank, "LUZ-1", _probe(), "run-boom")

    assert result.notes == []          # no crash — degraded to the (empty) accumulated result
    assert md == ["md r0"]             # blocks gathered before the crash still surface
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


# --- run_gather flag gate --- #
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

    assert spy["loop"] is False                        # controller NOT entered when the flag is off
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

    assert crawls == ["LUZ-158390"]                    # round 0 crawl; round 1 converged pre-crawl
    assert "Exploration:" in seen["reply"] and "converged" in seen["reply"]
    assert "2 nodes" in seen["reply"]                  # summarize_gather over the accumulated result


# --- B1: thin-seed structural climb runs BEFORE (and suppresses) memory recall --- #
async def test_thin_seed_climbs_to_parent_and_skips_memory_recall(monkeypatch):
    """B1: a thin container with a parent promotes the parent (real AC) and does NOT fall into
    memory recall — the drift source for a thin seed. See RESEARCH §7.3 B1."""
    from knowledge_gathering.explore import expand as expand_mod

    recalls: list[str] = []
    monkeypatch.setattr(expand_mod, "memory_self_seed",
                        lambda bank, seed, focus: (recalls.append(seed) or (["jira:BLED-1"], "prior")))

    new_seeds, md = await expand_mod.expansion_round(
        _bank(), _IssueClient(), seed="LUZ-159312", terms="functional performance test",
        thin=True, project="LUZ", title="Functional Test", parent="LUZ-156281", exclude=set())

    assert "jira:LUZ-156281" in new_seeds            # climbed to the structural parent
    assert "jira:BLED-1" not in new_seeds            # memory recall suppressed → no bleed
    assert recalls == []                             # G0 not even consulted
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

    assert recalls == ["LUZ-159312"]                 # G0 consulted (no parent to climb)
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

    assert "jira:LUZ-156281" not in new_seeds        # non-thin → no structural climb
    assert recalls == ["LUZ-159312"]                 # recall still runs
    assert not any("climbed" in m for m in md)


# --- B2: codegraph anchor — feed an attached code graph into EVERY round's focus + auto-resolve --- #
async def test_codegraph_anchor_leads_every_round_focus(monkeypatch):
    """B2 Part A: once a codegraph note is attached, its code-vocabulary tokens lead every later
    round's focus so exploration steers by the seed's real code, not memory drift. See §7.3 B2."""
    from common.models import CODEGRAPH
    from knowledge_gathering.executor.gather import SeedProbe

    async def fake_exp(bank_, client_, *, seed, terms, **k):
        return ["jira:NEXT"], []  # always something to crawl next

    seeds_seen: list[str] = []

    async def fake_crawl(client_, bank_, seed, *, extra_seeds=None, **k):
        seeds_seen.append(seed)
        if len(seeds_seen) == 1:  # round 0 attaches the code graph (as a client repo= would)
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

    # a round-1+ focus reflection carries the codegraph vocabulary — the anchor led the focus
    assert "paymentcontroller" in exploration_md.lower()


async def test_codegraph_auto_resolves_devpanel_repo_when_enabled(monkeypatch):
    """B2 Part B (opt-in): a dev-panel codegraph the seed crawl only RECORDED is auto-promoted and
    crawled (built) the next round, so the anchor grounds exploration without a manual repo=."""
    from common.models import CODEGRAPH, LinkRecord
    from knowledge_gathering.executor.gather import SeedProbe

    async def fake_exp(bank_, client_, *, seed, terms, **k):
        return [], []  # no fan-out promotions — the codegraph must come from auto-resolve/carry

    seeds_seen: list[str] = []

    async def fake_crawl(client_, bank_, seed, *, extra_seeds=None, **k):
        seeds_seen.append(seed)
        if seed == "codegraph:ws/repo":
            return CrawlResult(notes=[Note(id="codegraph:ws/repo", type=CODEGRAPH,
                                           title="ws/repo", synopsis="PaymentController endpoints")])
        # round 0: a recorded-only dev-panel codegraph link (not followed)
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

    assert "codegraph:ws/repo" in seeds_seen  # the recorded repo was promoted + crawled (built)


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

    assert "codegraph:ws/repo" not in seeds_seen  # default: recorded-only, not built


# --- B3: topic-coherence stop — a round that drifts off the SEED stops the loop --- #
async def test_off_seed_round_stops_the_loop(monkeypatch):
    """B3: round 1 discovers nodes sharing NO vocabulary with the seed's own neighborhood → the
    loop stops ('off-seed drift') instead of anchoring round 2 on the drift. See §7.3 B3."""
    from knowledge_gathering.executor.gather import SeedProbe

    async def fake_exp(bank_, client_, *, seed, terms, **k):
        return ["jira:NEXT"], []  # always a promoted seed so the next round can crawl

    crawls: list[str] = []

    async def fake_crawl(client_, bank_, seed, *, extra_seeds=None, **k):
        crawls.append(seed)
        if len(crawls) == 1:  # round 0 — on-seed neighborhood (defines the reference)
            return CrawlResult(notes=[_note("jira:LUZ-1", "billing dunning retry schedule")])
        # round 1 — a totally off-seed node (ePost zip-import), zero token overlap with the seed
        return CrawlResult(notes=[_note("jira:ZIP", "zipimport transfer metadata archive folders")])

    monkeypatch.setattr(explore_mod, "expansion_round", fake_exp)
    monkeypatch.setattr(explore_mod, "crawl", fake_crawl)
    monkeypatch.setenv("KGA_EXPLORE_MAX_ROUNDS", "5")  # generous — B3 must stop first, not the bound

    probe = SeedProbe(terms="billing dunning retry", thin=True, project="LUZ", title="Billing")
    _r, _md, expl = await _run_loop(_bank(), "LUZ-1", probe, "run-drift")

    assert len(crawls) == 2                      # round 0 + the drifted round 1, then STOP
    assert "off-seed drift" in expl              # reported as drift, not plain convergence


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
    monkeypatch.setenv("KGA_EXPLORE_MIN_COHERENCE", "0")  # B3 off

    probe = SeedProbe(terms="billing dunning retry", thin=True, project="LUZ", title="Billing")
    _r, _md, expl = await _run_loop(_bank(), "LUZ-1", probe, "run-nogate")

    assert len(crawls) == 3                       # runs to the round bound; B3 did not stop it
    assert "off-seed drift" not in expl


# --- B5: the loop gates round-≥1 promotions through the structural grounding check --- #
async def test_b5_gate_drops_ungrounded_promotions(monkeypatch):
    """B5 (opt-in): with grounding on, a round-1 promotion that does NOT connect to the seed's
    round-0 graph is dropped before it is crawled; a connected one is kept. See §7.3 B5."""
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

    # ground only ids containing GOOD — isolates the wiring from a real index/edge set
    monkeypatch.setattr(explore_mod, "graph_grounded",
                        lambda graph, cand, anchors: "GOOD" in cand)
    monkeypatch.setattr(explore_mod, "expansion_round", fake_exp)
    monkeypatch.setattr(explore_mod, "crawl", fake_crawl)
    monkeypatch.setenv("KGA_EXPLORE_GROUND_PROMOTIONS", "1")
    monkeypatch.setenv("KGA_EXPLORE_MIN_COHERENCE", "0")  # isolate B5 from B3
    monkeypatch.setenv("KGA_EXPLORE_MAX_ROUNDS", "3")

    probe = SeedProbe(terms="seed neighborhood", thin=True, project="LUZ", title="Seed")
    await _run_loop(_bank(), "LUZ-1", probe, "run-b5")

    assert "jira:GOOD-1" in crawls        # grounded promotion crawled
    assert "jira:BAD-1" not in crawls     # ungrounded promotion dropped by B5


# --- B6: negative-signal re-anchor — a rejected domain is pruned from the pack + focus --- #
async def test_b6_exclude_prunes_rejected_cluster(monkeypatch):
    """B6: re-running with exclude='zip import' prunes matching nodes from the pack (and steers the
    focus away), so one human correction re-anchors the loop off the bled cluster. See §7.3 B6."""
    from knowledge_gathering.executor.gather import SeedProbe

    async def fake_exp(bank_, client_, *, seed, terms, **k):
        return ["jira:NEXT"], []

    async def fake_crawl(client_, bank_, seed, *, extra_seeds=None, **k):
        return CrawlResult(notes=[
            _note("jira:BILL-1", "billing dunning retry"),
            _note("jira:ZIP-1", "zip import transfer metadata"),  # the rejected cluster
        ])

    monkeypatch.setattr(explore_mod, "expansion_round", fake_exp)
    monkeypatch.setattr(explore_mod, "crawl", fake_crawl)
    monkeypatch.setenv("KGA_EXPLORE_MAX_ROUNDS", "1")

    probe = SeedProbe(terms="billing dunning", thin=True, project="LUZ", title="Billing")
    result, _md, _expl = await explore_mod.run_explore_loop(
        None, None, None, "LUZ-1", probe, bank=_bank(), client=object(),
        extra_seeds=[], depth=1, scope=None, distiller=None, run_id="run-b6", exclude="zip import")

    ids = {n.id for n in result.notes}
    assert "jira:BILL-1" in ids          # on-topic node kept
    assert "jira:ZIP-1" not in ids       # rejected cluster pruned from the pack
