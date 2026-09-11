"""Tier-1 memory self-seed (roadmap G0) — pure memory-read, NO LLM."""

from __future__ import annotations

from common.memory.graph_index import match_index_nodes, rank_promotions
from common.models import INSIGHT
from knowledge_gathering.gather.seed import normalize_seed
from knowledge_gathering.monitoring import get_logger

log = get_logger("explore.self_seed")

_STOPWORDS = frozenset({
    "the", "and", "for", "with", "from", "this", "that", "are", "was",
    "not", "but", "all", "any", "has", "have", "its", "into", "when", "will",
})
_FETCHABLE = ("jira:", "confluence:")


def salient_tokens(text: str) -> list[str]:
    """Distinct usable tokens of `text` — lowercased, len >= 3, non-stopword, order-preserving."""
    return list(dict.fromkeys(t for tok in text.split() if len(t := tok.strip().lower()) >= 3 and t not in _STOPWORDS))


def _queries(seed_key: str, terms: str) -> list[str]:
    """Distinct match queries: the seed's own key (when usable) + each usable token in `terms`
    (`salient_tokens` already applied the len/stopword filter, so only the key needs guarding)."""
    key = seed_key.strip().lower()
    head = [key] if len(key) >= 3 and key not in _STOPWORDS else []
    return list(dict.fromkeys([*head, *salient_tokens(terms)]))


def _render(matched: dict[str, dict], *, limit: int = 8) -> str:
    """Compact markdown block for the gather reply — insight nodes called out first."""
    nodes = sorted(matched.values(), key=lambda n: n.get("id", ""))
    ordered = sorted(nodes, key=lambda n: (n.get("type") or "") != INSIGHT)
    lines = [f"Prior knowledge from memory ({len(nodes)} related node(s)):",
             *[f"- {n['id']} [{n.get('type', '?')}]" + (f" — {t}" if (t := n.get("title") or "") else "")
               for n in ordered[:limit]]]
    if len(ordered) > limit:
        lines.append(f"- … +{len(ordered) - limit} more (search-memory to list)")
    return "\n".join(lines)


def memory_self_seed(bank, seed: str, terms: str = "", *, max_seeds: int = 5) -> tuple[list[str], str]:
    """Return `(extra_seeds, prior_md)` from the memory index for `seed` (+ optional terms)."""
    try:
        self_id = normalize_seed(seed)
        queries = _queries(self_id.split(":", 1)[-1], terms)
        graph, _ = bank.load_index()
        matched = {nid: n for q in queries for n in match_index_nodes(graph, q)
                   if (nid := n.get("id", "")) and nid != self_id}
        if not matched:
            return [], ""
        extra_seeds = rank_promotions(graph, queries, prefixes=_FETCHABLE,
                                      max_seeds=max_seeds, exclude={self_id})
        return extra_seeds, _render(matched)
    except Exception as exc:  # noqa: BLE001 — self-seed must never break gather
        log.warning("memory self-seed skipped for %s (%s)", seed, exc)
        return [], ""


_FETCHABLE_TYPES = ("jira-issue", "confluence-page")


def _semantic_enabled() -> bool:
    """Opt-in gate (default OFF) — semantic seeding changes the carefully-tuned de-bias seeding, so"""
    import os

    return os.environ.get("MEMORY_SEMANTIC_SEED", "").lower() in ("1", "true", "yes", "on")


def _neighbors(graph, node_id: str) -> set[str]:
    """Ids sharing an index edge with `node_id` (either direction) — the seed's B5 anchor set."""
    out: set[str] = set()
    for e in graph.edges.values():
        src, tgt = e.get("source_id", ""), e.get("target", "")
        if src == node_id and tgt:
            out.add(tgt)
        elif tgt == node_id and src:
            out.add(src)
    return out


async def semantic_self_seed(bank, seed: str, terms: str = "", *, exclude: set[str] | None = None,
                             max_seeds: int = 5) -> tuple[list[str], str]:
    """G0.5: promote VECTOR-nearest fetchable prior seeds, each **B5-grounded** to the seed's graph"""
    exclude = set(exclude or ())
    try:
        from common.memory import retrieve

        if not _semantic_enabled() or retrieve.backend() == "gcs":
            return [], ""
        import itertools

        from common.memory.graph_index import graph_grounded
        from common.memory.pg import build_store
        from common.memory.pg.embed import aembed_query, embed_configured

        store = build_store()
        if store is None or not embed_configured():
            return [], ""
        self_id = normalize_seed(seed)
        graph, _ = bank.load_index()
        if not (anchors := _neighbors(graph, self_id)):
            return [], ""
        q_embed = await aembed_query(terms) if terms else None
        rows = await store.search(q_text=terms, q_embed=q_embed, types=list(_FETCHABLE_TYPES), k=max_seeds * 4)
        out = list(itertools.islice(
            (nid for r in rows if (nid := r.get("id", "")) and nid != self_id and nid not in exclude
             and nid.startswith(_FETCHABLE) and graph_grounded(graph, nid, anchors)), max_seeds))
        return out, ("\n".join([f"Semantically-related prior seeds ({len(out)}), grounded to this ticket:", *[f"- {i}" for i in out]]) if out else "")
    except Exception as exc:  # noqa: BLE001 — semantic seed must never break gather
        log.warning("semantic self-seed skipped for %s (%s)", seed, exc)
        return [], ""
