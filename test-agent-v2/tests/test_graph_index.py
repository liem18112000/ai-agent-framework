"""M1: the shared predicates moved to common.memory.graph_index; the explore.index shim re-exports."""

from __future__ import annotations

from common.memory import graph_index
from common.memory import graph_index as shim
from common.models import Graph


def _g(nodes, edges=()):
    g = Graph()
    for n in nodes:
        g.nodes[n["id"]] = n
    for e in edges:
        g.edges[f"{e['source_id']}->{e['target']}"] = e
    return g


def test_shim_reexports_the_same_objects():
    assert shim.match_index_nodes is graph_index.match_index_nodes
    assert shim.rank_promotions is graph_index.rank_promotions
    assert shim.graph_grounded is graph_index.graph_grounded


def test_match_index_nodes_behaviour():
    g = _g([{"id": "jira:LUZ-1", "type": "jira-issue", "title": "Login"},
            {"id": "confluence:9", "type": "confluence-page", "title": "Docs"}])
    assert {n["id"] for n in graph_index.match_index_nodes(g, "login")} == {"jira:LUZ-1"}
    assert {n["id"] for n in graph_index.match_index_nodes(g, "confluence-page")} == {"confluence:9"}
    assert len(graph_index.match_index_nodes(g, "")) == 2


def test_graph_grounded_structural_gate():
    g = _g(
        [{"id": "jira:LUZ-1", "type": "jira-issue", "title": ""}],
        edges=[{"source_id": "jira:LUZ-1", "target": "jira:EPIC-1"}],
    )
    assert graph_index.graph_grounded(g, "jira:EPIC-1", {"jira:EPIC-1"}) is True
    assert graph_index.graph_grounded(g, "jira:LUZ-1", {"jira:EPIC-1"}) is True
    assert graph_index.graph_grounded(g, "jira:FLOAT", {"jira:EPIC-1"}) is False
    assert graph_index.graph_grounded(g, "jira:FLOAT", set()) is True
