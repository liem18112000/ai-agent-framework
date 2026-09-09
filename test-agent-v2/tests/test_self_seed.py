"""G0 memory self-seed — `memory_self_seed` + the shared `match_index_nodes` predicate."""

from __future__ import annotations

import pytest

from common.memory.graph_index import match_index_nodes
from common.models import Graph
from knowledge_gathering.gather.explore.seeds.self_seed import memory_self_seed


def _graph(*nodes: dict) -> Graph:
    g = Graph()
    for n in nodes:
        g.nodes[n["id"]] = n
    return g


class _FakeBank:
    """Minimal bank: only `load_index()` is used by the self-seed."""

    def __init__(self, graph: Graph):
        self._graph = graph

    def load_index(self):
        return self._graph, 0


class _BrokenBank:
    def load_index(self):
        raise RuntimeError("GCS unavailable")


def _node(nid: str, ntype: str, title: str = "") -> dict:
    return {"id": nid, "type": ntype, "title": title}


def test_match_index_nodes_matches_id_title_type():
    g = _graph(
        _node("jira:LUZ-1", "jira-issue", "Login bug"),
        _node("confluence:9", "confluence-page", "Export spec"),
    )
    assert {n["id"] for n in match_index_nodes(g, "login")} == {"jira:LUZ-1"}
    assert {n["id"] for n in match_index_nodes(g, "luz-1")} == {"jira:LUZ-1"}
    assert {n["id"] for n in match_index_nodes(g, "confluence-page")} == {"confluence:9"}


def test_match_index_nodes_empty_query_returns_all():
    g = _graph(_node("jira:LUZ-1", "jira-issue"), _node("jira:LUZ-2", "jira-issue"))
    assert len(match_index_nodes(g, "")) == 2


def _pack_graph() -> Graph:
    return _graph(
        _node("jira:LUZ-158390", "jira-issue", "Export fails for restricted folders"),
        _node("jira:LUZ-158000", "jira-issue", "Export bug in folders"),
        _node("confluence:12345", "confluence-page", "Export spec"),
        _node("insight:run-6f2a:Q-biz-1", "insight", "Export must include restricted folders"),
        _node("external-web:https://ex/x", "external-web", "Export article"),
        _node("jira:ABC-1", "jira-issue", "Login timeout"),
    )


def test_promotes_matching_fetchable_nodes_and_excludes_seed_and_externals():
    bank = _FakeBank(_pack_graph())
    extra_seeds, prior_md = memory_self_seed(bank, "LUZ-158390", "export restricted folders")

    assert "jira:LUZ-158000" in extra_seeds
    assert "confluence:12345" in extra_seeds
    assert "jira:LUZ-158390" not in extra_seeds
    assert "external-web:https://ex/x" not in extra_seeds
    assert "insight:run-6f2a:Q-biz-1" not in extra_seeds
    assert "jira:ABC-1" not in extra_seeds
    assert prior_md and "insight" in prior_md
    assert "jira:LUZ-158390" not in prior_md


def test_extra_seeds_are_stable_sorted_and_capped():
    nodes = [_node(f"jira:AAA-{i}", "jira-issue", "export thing") for i in range(1, 8)]
    nodes.append(_node("jira:LUZ-1", "jira-issue", "Export seed"))
    bank = _FakeBank(_graph(*nodes))

    extra_seeds, _ = memory_self_seed(bank, "LUZ-1", "export", max_seeds=3)
    assert extra_seeds == ["jira:AAA-1", "jira:AAA-2", "jira:AAA-3"]


def test_no_match_yields_empty_seeds_and_blank_md():
    bank = _FakeBank(_graph(_node("jira:OTHER-9", "jira-issue", "Totally different thing")))
    extra_seeds, prior_md = memory_self_seed(bank, "LUZ-158390", "nonexistentterm")
    assert extra_seeds == [] and prior_md == ""


def test_empty_index_yields_empty():
    assert memory_self_seed(_FakeBank(Graph()), "LUZ-1", "export") == ([], "")


def test_broken_bank_never_raises():
    assert memory_self_seed(_BrokenBank(), "LUZ-1", "export") == ([], "")


def test_insight_only_match_still_surfaces_but_promotes_nothing():
    g = _graph(_node("insight:run-x:Q1", "insight", "Export edge case matters"))
    extra_seeds, prior_md = memory_self_seed(_FakeBank(g), "LUZ-1", "export")
    assert extra_seeds == []
    assert prior_md and "insight" in prior_md


@pytest.mark.parametrize("terms", ["", "a of to"])
def test_key_only_and_stopword_tokens(terms):
    g = _graph(_node("jira:LUZ-999", "jira-issue", "Unrelated"))
    extra_seeds, prior_md = memory_self_seed(_FakeBank(g), "LUZ-1", terms)
    assert extra_seeds == [] and prior_md == ""


def test_hub_domain_suppressed_rare_match_promoted():
    """B4: in a LARGE index dominated by one domain, a generic hub token ('test') that matches that"""
    zip_nodes = [_node(f"jira:ZIP-{i}", "jira-issue", "zip import transfer test") for i in range(1, 26)]
    bill = _node("jira:BILL-1", "jira-issue", "billing dunning retry test")
    bank = _FakeBank(_graph(*zip_nodes, bill))

    extra_seeds, _ = memory_self_seed(bank, "LUZ-1", "billing dunning test", max_seeds=5)

    assert extra_seeds == ["jira:BILL-1"]
    assert not any(s.startswith("jira:ZIP-") for s in extra_seeds)


def test_small_index_ranks_by_idf_without_hub_suppression():
    """Below the saturation threshold there is nothing to bleed: a token matching most of a tiny"""
    bank = _FakeBank(_graph(
        _node("jira:A-1", "jira-issue", "export folders"),
        _node("jira:A-2", "jira-issue", "export folders"),
        _node("jira:LUZ-1", "jira-issue", "export seed"),
    ))
    extra_seeds, _ = memory_self_seed(bank, "LUZ-1", "export", max_seeds=5)
    assert set(extra_seeds) == {"jira:A-1", "jira:A-2"}


def test_graph_grounded_requires_structural_connection():
    """B5: graph_grounded is True only when the candidate IS an anchor or shares an index edge with"""
    from common.memory.graph_index import graph_grounded

    g = Graph()
    g.nodes = {n["id"]: n for n in (
        _node("jira:EPIC-1", "jira-issue", "epic"),
        _node("jira:CONNECTED-1", "jira-issue", "child of epic"),
        _node("jira:FLOATING-1", "jira-issue", "unrelated but term-near"),
    )}
    g.edges = {"jira:CONNECTED-1->jira:EPIC-1": {"source_id": "jira:CONNECTED-1", "target": "jira:EPIC-1"}}
    anchors = {"jira:EPIC-1"}

    assert graph_grounded(g, "jira:EPIC-1", anchors) is True
    assert graph_grounded(g, "jira:CONNECTED-1", anchors) is True
    assert graph_grounded(g, "jira:FLOATING-1", anchors) is False
    assert graph_grounded(g, "jira:FLOATING-1", set()) is True
