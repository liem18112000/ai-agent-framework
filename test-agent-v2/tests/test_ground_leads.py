"""G4 GROUNDING GATE — `ground_leads` (unit) + its wiring into `run_gather`."""

from __future__ import annotations

import types

from common.models import Graph
from knowledge_gathering.executor import gather as gather_mod
from knowledge_gathering.explore import expand as expand_mod
from knowledge_gathering.explore.ground_leads import ground_leads
from knowledge_gathering.loop import CrawlResult


def _node(nid: str, ntype: str = "jira-issue", title: str = "") -> dict:
    return {"id": nid, "type": ntype, "title": title}


def _graph(*nodes: dict) -> Graph:
    g = Graph()
    for n in nodes:
        g.nodes[n["id"]] = n
    return g


class _FakeBank:
    def __init__(self, graph: Graph):
        self._graph = graph

    def load_index(self):
        return self._graph, 0


class _BrokenBank:
    def load_index(self):
        raise RuntimeError("GCS unavailable")


class _FakeSearchClient:
    """Maps a search query -> jira/confluence hit lists, and counts calls (search budget check)."""

    def __init__(self, jira_by_q=None, conf_by_q=None):
        self._jira_by_q = jira_by_q or {}
        self._conf_by_q = conf_by_q or {}
        self.jql_calls = 0
        self.cql_calls = 0

    @staticmethod
    def _lookup(table, query):
        for token, hits in table.items():
            if token in query:
                return hits
        return []

    async def search_jql(self, jql, *, max_results=10):
        self.jql_calls += 1
        return self._lookup(self._jira_by_q, jql)

    async def search_cql(self, cql, *, limit=10):
        self.cql_calls += 1
        return self._lookup(self._conf_by_q, cql)


async def test_lead_grounded_in_memory_becomes_seed():
    bank = _FakeBank(_graph(_node("jira:LUZ-500", title="audit log retention")))
    client = _FakeSearchClient()
    grounded, unconfirmed, md = await ground_leads(
        client, bank, ["audit log"], project="LUZ", exclude=set())
    assert grounded == ["jira:LUZ-500"]
    assert unconfirmed == []
    assert client.jql_calls == 0 and client.cql_calls == 0
    assert "grounded 1, unconfirmed 0" in md and "jira:LUZ-500" in md


async def test_lead_grounded_in_atlassian_when_memory_misses():
    bank = _FakeBank(Graph())
    client = _FakeSearchClient(jira_by_q={"bulk export": ["LUZ-77"]})
    grounded, unconfirmed, _ = await ground_leads(
        client, bank, ["bulk export"], project="LUZ", exclude=set())
    assert grounded == ["jira:LUZ-77"]
    assert unconfirmed == []
    assert client.jql_calls == 1


async def test_unconfirmed_lead_is_not_a_seed():
    bank = _FakeBank(Graph())
    client = _FakeSearchClient()
    grounded, unconfirmed, md = await ground_leads(
        client, bank, ["ghost feature"], project="LUZ", exclude=set())
    assert grounded == []
    assert unconfirmed == ["ghost feature"]
    assert "ghost feature" in md and "chase manually" in md
    assert "grounded 0, unconfirmed 1" in md


async def test_memory_then_atlassian_grounding_mixed():
    bank = _FakeBank(_graph(_node("jira:LUZ-500", title="audit log retention")))
    client = _FakeSearchClient(jira_by_q={"bulk export": ["LUZ-77"]})
    grounded, unconfirmed, _ = await ground_leads(
        client, bank, ["audit log", "bulk export", "ghost feature"],
        project="LUZ", exclude=set())
    assert grounded == ["jira:LUZ-500", "jira:LUZ-77"]
    assert unconfirmed == ["ghost feature"]
    assert client.jql_calls == 2


async def test_excluded_ids_are_dropped_from_seeds():
    bank = _FakeBank(_graph(_node("jira:LUZ-500", title="audit log")))
    grounded, unconfirmed, _ = await ground_leads(
        _FakeSearchClient(), bank, ["audit log"],
        project="LUZ", exclude={"jira:LUZ-500"})
    assert grounded == []
    assert unconfirmed == []


async def test_max_seeds_cap_and_stable_sort():
    nodes = [_node(f"jira:LUZ-{i}", title="export thing") for i in range(1, 8)]
    bank = _FakeBank(_graph(*nodes))
    grounded, _, _ = await ground_leads(
        _FakeSearchClient(), bank, ["export"], project="LUZ", exclude=set(), max_seeds=3)
    assert grounded == ["jira:LUZ-1", "jira:LUZ-2", "jira:LUZ-3"]


async def test_max_searches_budget_honored():
    bank = _FakeBank(Graph())
    client = _FakeSearchClient(
        jira_by_q={"alpha": ["LUZ-1"], "beta": ["LUZ-2"], "gamma": ["LUZ-3"]})
    grounded, unconfirmed, _ = await ground_leads(
        client, bank, ["alpha", "beta", "gamma"], project="LUZ", exclude=set(), max_searches=1)
    assert client.jql_calls == 1
    assert grounded == ["jira:LUZ-1"]
    assert unconfirmed == ["beta", "gamma"]


async def test_empty_leads_yields_blank():
    assert await ground_leads(_FakeSearchClient(), _FakeBank(Graph()), [],
                              project=None, exclude=set()) == ([], [], "")


async def test_blank_leads_are_deduped_away():
    assert await ground_leads(_FakeSearchClient(), _FakeBank(Graph()), ["  ", "", "  "],
                              project=None, exclude=set()) == ([], [], "")


async def test_broken_bank_never_raises_but_atlassian_still_works():
    client = _FakeSearchClient(jira_by_q={"export": ["LUZ-9"]})
    grounded, unconfirmed, _ = await ground_leads(
        client, _BrokenBank(), ["export"], project="LUZ", exclude=set())
    assert grounded == ["jira:LUZ-9"]
    assert unconfirmed == []


async def test_any_failure_degrades_to_empty():
    class _Boom:
        def load_index(self):
            return Graph(), 0

    class _BoomClient:
        async def search_jql(self, *a, **k):
            raise RuntimeError("x")

        async def search_cql(self, *a, **k):
            raise RuntimeError("y")

    grounded, unconfirmed, _ = await ground_leads(
        _BoomClient(), _Boom(), ["z"], project=None, exclude=set())
    assert grounded == [] and unconfirmed == ["z"]


class _Ctx:
    context_id = "run-x"


class _IssueClient:
    """One thin Jira issue (short body, no links/subtasks) so the probe yields a title."""

    def __init__(self, summary="Export fails for restricted folders", labels=("earchive",)):
        self._issue = {"fields": {
            "summary": summary,
            "description": {"type": "doc", "version": 1, "content": []},
            "issuelinks": [], "subtasks": [], "labels": list(labels), "components": [],
        }}
        self.jql_calls = 0

    async def get_issue(self, key):
        return self._issue

    async def search_jql(self, jql, *, max_results=10):
        self.jql_calls += 1
        return []

    async def search_cql(self, cql, *, limit=10):
        return []


async def _run_gather(monkeypatch, *, flag_on, leads=None, grounded=None, unconfirmed=None):
    """Drive run_gather with G0/G1/G4-internals/crawl/reply stubbed; return what each phase saw."""
    seen = {"lead_calls": 0, "extra_seeds": None, "reply": None, "ground_calls": 0}

    def fake_ask_llm(title, description="", labels=None):
        seen["lead_calls"] += 1
        return leads if leads is not None else ["a lead"]

    async def fake_ground(client, bank, leads_in, *, project=None, exclude=None,
                          max_seeds=5, max_searches=4):
        seen["ground_calls"] += 1
        md = "External-LLM leads — grounded X, unconfirmed Y:" if leads_in else ""
        return (grounded or []), (unconfirmed or []), md

    def fake_self_seed(bank, seed, terms=""):
        return [], ""

    async def fake_search(client, terms, *, project=None, exclude=None, **kw):
        return [], ""

    async def fake_crawl(*a, extra_seeds=None, **k):
        seen["extra_seeds"] = list(extra_seeds or [])
        return CrawlResult()

    async def fake_reply(context, event_queue, text):
        seen["reply"] = text

    monkeypatch.setattr(expand_mod, "ask_llm_leads", fake_ask_llm)
    monkeypatch.setattr(expand_mod, "ground_leads", fake_ground)
    monkeypatch.setattr(expand_mod, "memory_self_seed", fake_self_seed)
    monkeypatch.setattr(expand_mod, "atlassian_search_seeds", fake_search)
    monkeypatch.setattr(gather_mod, "crawl", fake_crawl)
    monkeypatch.setattr(gather_mod, "reply", fake_reply)
    monkeypatch.delenv("KGA_LLM_HYPOTHESIZE", raising=False)
    if flag_on:
        monkeypatch.setenv("KGA_LLM_LEADS", "1")
    else:
        monkeypatch.delenv("KGA_LLM_LEADS", raising=False)

    ex = types.SimpleNamespace(_client=_IssueClient(), _bank=object(), _distiller=None)
    await gather_mod.run_gather(ex, _Ctx(), object(), "gather LUZ-158390 depth 1")
    return seen


async def test_flag_off_makes_no_lead_call(monkeypatch):
    seen = await _run_gather(monkeypatch, flag_on=False)
    assert seen["lead_calls"] == 0 and seen["ground_calls"] == 0
    assert "External-LLM leads" not in (seen["reply"] or "")


async def test_flag_on_grounded_leads_reach_extra_seeds(monkeypatch):
    seen = await _run_gather(
        monkeypatch, flag_on=True,
        leads=["audit log", "ghost feature"],
        grounded=["jira:LUZ-77"], unconfirmed=["ghost feature"])
    assert seen["lead_calls"] == 1
    assert "jira:LUZ-77" in seen["extra_seeds"]
    assert "ghost feature" not in seen["extra_seeds"]
    assert "External-LLM leads" in seen["reply"]


async def test_flag_on_all_unconfirmed_adds_no_seeds(monkeypatch):
    seen = await _run_gather(
        monkeypatch, flag_on=True, leads=["ghost"], grounded=[], unconfirmed=["ghost"])
    assert seen["lead_calls"] == 1
    assert seen["extra_seeds"] == []
