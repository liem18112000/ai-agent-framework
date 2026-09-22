"""G4 GROUNDING GATE — `ground_leads` (unit) + its wiring into the pre-crawl fan-out."""

from __future__ import annotations

from common.models import Graph
from knowledge_gathering.gather.explore import expand as expand_mod
from knowledge_gathering.gather.explore.seeds.ground_leads import ground_leads


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


# --- P2: expansion_round runs the DETERMINISTIC ground_leads gate on caller-supplied leads --------
# (The LLM lead enumeration moved out to the GatherAgent under D15; expansion_round only grounds a
# supplied `leads` list now. `expand_mod` is imported at the top of this module.)


def _stub_deterministic_phases(monkeypatch):
    """Silence G0/G1 so a wiring test observes only the leads-grounding path."""
    monkeypatch.setattr(expand_mod, "memory_self_seed", lambda bank, seed, focus="": ([], ""))

    async def _sem(bank, seed, focus, *, exclude=None):
        return [], ""

    async def _search(client, terms, *, project=None, exclude=None, **kw):
        return [], ""

    monkeypatch.setattr(expand_mod, "semantic_self_seed", _sem)
    monkeypatch.setattr(expand_mod, "atlassian_search_seeds", _search)


async def test_expansion_round_grounds_supplied_leads(monkeypatch):
    _stub_deterministic_phases(monkeypatch)
    seen = {"calls": 0, "leads_in": None}

    async def fake_ground(client, bank, leads_in, *, project=None, exclude=None,
                          max_seeds=5, max_searches=4):
        seen["calls"] += 1
        seen["leads_in"] = list(leads_in)
        return ["jira:LUZ-77"], ["ghost feature"], "External-LLM leads — grounded 1, unconfirmed 1:"

    monkeypatch.setattr(expand_mod, "ground_leads", fake_ground)
    new_seeds, md = await expand_mod.expansion_round(
        _FakeBank(Graph()), _FakeSearchClient(), seed="LUZ-158390", terms="export",
        thin=False, project="LUZ", leads=["audit log", "ghost feature"])
    assert seen["calls"] == 1
    assert seen["leads_in"] == ["audit log", "ghost feature"]
    assert "jira:LUZ-77" in new_seeds
    assert "ghost feature" not in new_seeds
    assert any("External-LLM leads" in m for m in md)


async def test_expansion_round_no_leads_skips_grounding(monkeypatch):
    _stub_deterministic_phases(monkeypatch)
    calls = {"n": 0}

    async def fake_ground(*a, **k):
        calls["n"] += 1
        return [], [], ""

    monkeypatch.setattr(expand_mod, "ground_leads", fake_ground)
    new_seeds, md = await expand_mod.expansion_round(
        _FakeBank(Graph()), _FakeSearchClient(), seed="LUZ-158390", terms="export",
        thin=False, project="LUZ", leads=None)
    assert calls["n"] == 0
    assert new_seeds == []
    assert not any("External-LLM leads" in m for m in md)


async def test_expansion_round_empty_leads_skips_grounding(monkeypatch):
    _stub_deterministic_phases(monkeypatch)
    calls = {"n": 0}

    async def fake_ground(*a, **k):
        calls["n"] += 1
        return [], [], ""

    monkeypatch.setattr(expand_mod, "ground_leads", fake_ground)
    _new_seeds, _md = await expand_mod.expansion_round(
        _FakeBank(Graph()), _FakeSearchClient(), seed="LUZ-158390", terms="export",
        thin=False, project="LUZ", leads=[])
    assert calls["n"] == 0


# --- P3: the GatherAgent always drives the leads LlmAgent (D15) ------------------------------------

async def test_gather_flag_on_runs_lead_planner_and_grounds(monkeypatch):
    from tests.conftest import drive_gather_agent, fake_model
    from tests.eval.harness import recorded_client

    model = fake_model('{"phrases":["audit log", "ghost feature"]}')
    reply, _bank = await drive_gather_agent(
        "LUZ-501", monkeypatch, client=recorded_client("eval_rich"), leads_model=model)
    assert "Gather complete" in reply
    assert len(model.calls) == 1
    assert "External-LLM leads" in reply           # grounding gate ran on the planner's phrases


async def test_gather_flag_on_junk_reply_degrades(monkeypatch):
    from tests.conftest import drive_gather_agent, fake_model
    from tests.eval.harness import recorded_client

    model = fake_model("not json at all")
    reply, _bank = await drive_gather_agent(
        "LUZ-501", monkeypatch, client=recorded_client("eval_rich"), leads_model=model)
    assert "Gather complete" in reply
    assert len(model.calls) == 1
    assert "External-LLM leads" not in reply       # degraded to no leads
