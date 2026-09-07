"""Shared memory-index predicates — dependency-free (graph dict shape only).

`match_index_nodes` (term match), `rank_promotions` (B4 IDF hub-penalty), `graph_grounded` (B5
structural gate), shared by the explore tiers + `search-memory` without depending on `executor`.
"""

from __future__ import annotations

import math


def match_index_nodes(graph, query: str) -> list[dict]:
    """Index nodes whose id / title / type contains `query` (case-insensitive); empty query → all.
    The single match predicate reused by `search-memory` and G0 self-seed — don't duplicate it."""
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


# Below this size there's no domain saturation to bleed → skip hub suppression, rank by plain idf.
_HUB_MIN_INDEX = 20


def rank_promotions(
    graph, queries: list[str], *, prefixes: tuple[str, ...], max_seeds: int,
    exclude: set[str] | None = None, hub_ratio: float = 0.4,
) -> list[str]:
    """IDF-rarity rank of index nodes matched by `queries` — the B4 hub-penalty de-bias.

    A saturated domain floods a large index: its generic tokens match a huge share of nodes and
    would recall that domain for ANY seed. Once saturated (`>= _HUB_MIN_INDEX`), HUB tokens
    (`df/N > hub_ratio`) are suppressed; every remaining match scores by `idf = ln(N/(1+df))`, so
    nodes tied by RARE tokens rank first (IDF rarity IS the per-domain cap). Below the threshold,
    plain idf. Returns up to `max_seeds` promotable (`prefixes`) ids, rarity-desc, id-asc for ties.
    """
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
            continue  # unmatched, or a hub token too common in a big index to be specific
        idf = math.log(n_total / (1 + df))
        for node in hits:
            nid = node.get("id", "")
            if nid.startswith(prefixes) and nid not in exclude:
                scores[nid] = scores.get(nid, 0.0) + idf
    ranked = sorted(scores, key=lambda nid: (-scores[nid], nid))
    return ranked[:max_seeds]


def graph_grounded(graph, candidate: str, anchors: set[str]) -> bool:
    """True if `candidate` STRUCTURALLY connects to the seed's graph (the B5 grounding gate).

    Connection = candidate IS an anchor, or an index edge links it to an anchor (shared epic/
    component/codegraph/link, either direction). Term-match nearness alone is NOT enough — that's
    how a biased domain bleeds in. Empty anchors → True (nothing to gate against).
    """
    if not anchors or candidate in anchors:
        return True
    for e in graph.edges.values():
        src, tgt = e.get("source_id", ""), e.get("target", "")
        if (candidate == src and tgt in anchors) or (candidate == tgt and src in anchors):
            return True
    return False
