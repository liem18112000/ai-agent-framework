"""G0 memory self-seed — `memory_self_seed` + the shared `match_index_nodes` predicate.

Pure in-memory: a tiny fake bank returns a real Graph index; no GCS, no network, no LLM.
"""

from __future__ import annotations

import pytest

from common.models import Graph
from knowledge_gathering.explore.index import match_index_nodes
from knowledge_gathering.explore.self_seed import memory_self_seed


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


# --- match_index_nodes (the shared predicate) --- #

def test_match_index_nodes_matches_id_title_type():
    g = _graph(
        _node("jira:LUZ-1", "jira-issue", "Login bug"),
        _node("confluence:9", "confluence-page", "Export spec"),
    )
    assert {n["id"] for n in match_index_nodes(g, "login")} == {"jira:LUZ-1"}       # title
    assert {n["id"] for n in match_index_nodes(g, "luz-1")} == {"jira:LUZ-1"}       # id
    assert {n["id"] for n in match_index_nodes(g, "confluence-page")} == {"confluence:9"}  # type


def test_match_index_nodes_empty_query_returns_all():
    g = _graph(_node("jira:LUZ-1", "jira-issue"), _node("jira:LUZ-2", "jira-issue"))
    assert len(match_index_nodes(g, "")) == 2


# --- memory_self_seed --- #

def _pack_graph() -> Graph:
    return _graph(
        _node("jira:LUZ-158390", "jira-issue", "Export fails for restricted folders"),  # the seed
        _node("jira:LUZ-158000", "jira-issue", "Export bug in folders"),                # prior, fetchable
        _node("confluence:12345", "confluence-page", "Export spec"),                    # prior, fetchable
        _node("insight:run-6f2a:Q-biz-1", "insight", "Export must include restricted folders"),
        _node("external-web:https://ex/x", "external-web", "Export article"),           # matched, NOT fetchable
        _node("jira:ABC-1", "jira-issue", "Login timeout"),                             # unrelated
    )


def test_promotes_matching_fetchable_nodes_and_excludes_seed_and_externals():
    bank = _FakeBank(_pack_graph())
    extra_seeds, prior_md = memory_self_seed(bank, "LUZ-158390", "export restricted folders")

    # (i) fetchable prior jira/confluence nodes are promoted
    assert "jira:LUZ-158000" in extra_seeds
    assert "confluence:12345" in extra_seeds
    # (ii) the seed itself is excluded
    assert "jira:LUZ-158390" not in extra_seeds
    # (iii) non-fetchable / external / insight nodes are not promoted
    assert "external-web:https://ex/x" not in extra_seeds
    assert "insight:run-6f2a:Q-biz-1" not in extra_seeds
    # unrelated node never matched at all
    assert "jira:ABC-1" not in extra_seeds
    # (vi) prior_md is non-empty and calls out the insight
    assert prior_md and "insight" in prior_md
    assert "jira:LUZ-158390" not in prior_md  # seed excluded here too


def test_extra_seeds_are_stable_sorted_and_capped():
    nodes = [_node(f"jira:AAA-{i}", "jira-issue", "export thing") for i in range(1, 8)]
    nodes.append(_node("jira:LUZ-1", "jira-issue", "Export seed"))  # the seed, excluded
    bank = _FakeBank(_graph(*nodes))

    extra_seeds, _ = memory_self_seed(bank, "LUZ-1", "export", max_seeds=3)
    assert extra_seeds == ["jira:AAA-1", "jira:AAA-2", "jira:AAA-3"]  # (iv) cap + stable sort


def test_no_match_yields_empty_seeds_and_blank_md():
    bank = _FakeBank(_graph(_node("jira:OTHER-9", "jira-issue", "Totally different thing")))
    extra_seeds, prior_md = memory_self_seed(bank, "LUZ-158390", "nonexistentterm")
    assert extra_seeds == [] and prior_md == ""  # (vi) blank md when nothing matches


def test_empty_index_yields_empty():
    assert memory_self_seed(_FakeBank(Graph()), "LUZ-1", "export") == ([], "")


def test_broken_bank_never_raises():
    # (v) any failure degrades to ([], "") — self-seed must never break gather
    assert memory_self_seed(_BrokenBank(), "LUZ-1", "export") == ([], "")


def test_insight_only_match_still_surfaces_but_promotes_nothing():
    g = _graph(_node("insight:run-x:Q1", "insight", "Export edge case matters"))
    extra_seeds, prior_md = memory_self_seed(_FakeBank(g), "LUZ-1", "export")
    assert extra_seeds == []            # insight is not fetchable
    assert prior_md and "insight" in prior_md


@pytest.mark.parametrize("terms", ["", "a of to"])  # only short/stopword tokens
def test_key_only_and_stopword_tokens(terms):
    # With no usable terms, matching falls back to the bare key; here nothing shares it.
    g = _graph(_node("jira:LUZ-999", "jira-issue", "Unrelated"))
    extra_seeds, prior_md = memory_self_seed(_FakeBank(g), "LUZ-1", terms)
    assert extra_seeds == [] and prior_md == ""


# --- B4: IDF hub-penalty — a saturated domain no longer floods promotions for an unrelated seed --- #
def test_hub_domain_suppressed_rare_match_promoted():
    """B4: in a LARGE index dominated by one domain, a generic hub token ('test') that matches that
    whole domain is suppressed, so it can't recall it for an unrelated seed; only the rare, seed-
    specific match ('billing'/'dunning') is promoted. See RESEARCH §7.3 B4."""
    zip_nodes = [_node(f"jira:ZIP-{i}", "jira-issue", "zip import transfer test") for i in range(1, 26)]
    bill = _node("jira:BILL-1", "jira-issue", "billing dunning retry test")  # the one relevant prior
    bank = _FakeBank(_graph(*zip_nodes, bill))

    extra_seeds, _ = memory_self_seed(bank, "LUZ-1", "billing dunning test", max_seeds=5)

    assert extra_seeds == ["jira:BILL-1"]                       # rare-token match only
    assert not any(s.startswith("jira:ZIP-") for s in extra_seeds)  # hub domain suppressed


def test_small_index_ranks_by_idf_without_hub_suppression():
    """Below the saturation threshold there is nothing to bleed: a token matching most of a tiny
    index is NOT suppressed, so its matches are still promoted (ranked by idf)."""
    bank = _FakeBank(_graph(
        _node("jira:A-1", "jira-issue", "export folders"),
        _node("jira:A-2", "jira-issue", "export folders"),
        _node("jira:LUZ-1", "jira-issue", "export seed"),  # the seed, excluded
    ))
    extra_seeds, _ = memory_self_seed(bank, "LUZ-1", "export", max_seeds=5)
    assert set(extra_seeds) == {"jira:A-1", "jira:A-2"}  # small index → no suppression


# --- B5: structural grounding predicate — connection to the seed graph, not term-nearness --- #
def test_graph_grounded_requires_structural_connection():
    """B5: graph_grounded is True only when the candidate IS an anchor or shares an index edge with
    one — a term-near but disconnected node is NOT grounded. See RESEARCH §7.3 B5."""
    from knowledge_gathering.explore.index import graph_grounded

    g = Graph()
    g.nodes = {n["id"]: n for n in (
        _node("jira:EPIC-1", "jira-issue", "epic"),
        _node("jira:CONNECTED-1", "jira-issue", "child of epic"),
        _node("jira:FLOATING-1", "jira-issue", "unrelated but term-near"),
    )}
    g.edges = {"jira:CONNECTED-1->jira:EPIC-1": {"source_id": "jira:CONNECTED-1", "target": "jira:EPIC-1"}}
    anchors = {"jira:EPIC-1"}

    assert graph_grounded(g, "jira:EPIC-1", anchors) is True        # is itself an anchor
    assert graph_grounded(g, "jira:CONNECTED-1", anchors) is True   # shares an edge with the anchor
    assert graph_grounded(g, "jira:FLOATING-1", anchors) is False   # term-near but disconnected
    assert graph_grounded(g, "jira:FLOATING-1", set()) is True      # no anchors → nothing to gate
