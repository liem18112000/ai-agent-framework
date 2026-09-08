"""Shared memory-index predicates — dependency-free (graph dict shape only)."""

from __future__ import annotations

import math


def match_index_nodes(graph, query: str) -> list[dict]:
    """Index nodes whose id / title / type contains `query` (case-insensitive); empty query → all."""
    nodes = list(graph.nodes.values())
    q = query.lower()
    if not q:
        return nodes
    return [
        n for n in nodes
        if q in n.get("id", "").lower()
        or q in (n.get("title") or "").lower()
        or q in (n.get("type") or "").lower()
    ]


_HUB_MIN_INDEX = 20


def rank_promotions(
    graph, queries: list[str], *, prefixes: tuple[str, ...], max_seeds: int,
    exclude: set[str] | None = None, hub_ratio: float = 0.4,
) -> list[str]:
    """IDF-rarity rank of index nodes matched by `queries` — the B4 hub-penalty de-bias."""
    n_total = max(len(graph.nodes), 1)
    suppress_hubs = n_total >= _HUB_MIN_INDEX
    exclude = exclude or set()
    scores: dict[str, float] = {}
    for q in queries:
        if not q:
            continue
        hits = match_index_nodes(graph, q)
        df = len(hits)
        if df == 0 or (suppress_hubs and df / n_total > hub_ratio):
            continue
        idf = math.log(n_total / (1 + df))
        for node in hits:
            nid = node.get("id", "")
            if nid.startswith(prefixes) and nid not in exclude:
                scores[nid] = scores.get(nid, 0.0) + idf
    ranked = sorted(scores, key=lambda nid: (-scores[nid], nid))
    return ranked[:max_seeds]


def graph_grounded(graph, candidate: str, anchors: set[str]) -> bool:
    """True if `candidate` STRUCTURALLY connects to the seed's graph (the B5 grounding gate)."""
    if not anchors or candidate in anchors:
        return True
    for e in graph.edges.values():
        src, tgt = e.get("source_id", ""), e.get("target", "")
        if (candidate == src and tgt in anchors) or (candidate == tgt and src in anchors):
            return True
    return False
