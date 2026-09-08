"""Tier-1 memory self-seed (roadmap G0) — pure memory-read, NO LLM."""

from __future__ import annotations

from common.models import INSIGHT
from knowledge_gathering.explore.index import match_index_nodes, rank_promotions
from knowledge_gathering.loop.seed import normalize_seed
from knowledge_gathering.monitoring import get_logger

log = get_logger("explore.self_seed")

_STOPWORDS = frozenset({
    "the", "and", "for", "with", "from", "this", "that", "are", "was",
    "not", "but", "all", "any", "has", "have", "its", "into", "when", "will",
})
_FETCHABLE = ("jira:", "confluence:")


def salient_tokens(text: str) -> list[str]:
    """Distinct usable tokens of `text` — lowercased, len >= 3, non-stopword, order-preserving."""
    out: list[str] = []
    for tok in text.split():
        t = tok.strip().lower()
        if len(t) >= 3 and t not in _STOPWORDS and t not in out:
            out.append(t)
    return out


def _queries(seed_key: str, terms: str) -> list[str]:
    """Distinct match queries: the seed's own key + each usable token in `terms`."""
    out: list[str] = []
    for tok in [seed_key.strip().lower(), *salient_tokens(terms)]:
        if len(tok) >= 3 and tok not in _STOPWORDS and tok not in out:
            out.append(tok)
    return out


def _render(matched: dict[str, dict], *, limit: int = 8) -> str:
    """Compact markdown block for the gather reply — insight nodes called out first."""
    nodes = sorted(matched.values(), key=lambda n: n.get("id", ""))
    insights = [n for n in nodes if (n.get("type") or "") == INSIGHT]
    others = [n for n in nodes if (n.get("type") or "") != INSIGHT]
    ordered = insights + others
    lines = [f"Prior knowledge from memory ({len(nodes)} related node(s)):"]
    for n in ordered[:limit]:
        title = n.get("title") or ""
        lines.append(f"- {n['id']} [{n.get('type', '?')}]" + (f" — {title}" if title else ""))
    if len(ordered) > limit:
        lines.append(f"- … +{len(ordered) - limit} more (search-memory to list)")
    return "\n".join(lines)


def memory_self_seed(bank, seed: str, terms: str = "", *, max_seeds: int = 5) -> tuple[list[str], str]:
    """Return `(extra_seeds, prior_md)` from the memory index for `seed` (+ optional terms)."""
    try:
        self_id = normalize_seed(seed)
        seed_key = self_id.split(":", 1)[-1]
        queries = _queries(seed_key, terms)
        graph, _ = bank.load_index()
        matched: dict[str, dict] = {}
        for q in queries:
            for n in match_index_nodes(graph, q):
                nid = n.get("id", "")
                if nid and nid != self_id:
                    matched[nid] = n
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


def _render_semantic(ids: list[str]) -> str:
    return "\n".join([f"Semantically-related prior seeds ({len(ids)}), grounded to this ticket:",
                      *[f"- {i}" for i in ids]])


async def semantic_self_seed(bank, seed: str, terms: str = "", *, exclude: set[str] | None = None,
                             max_seeds: int = 5) -> tuple[list[str], str]:
    """G0.5: promote VECTOR-nearest fetchable prior seeds, each **B5-grounded** to the seed's graph"""
    exclude = set(exclude or ())
    try:
        from common.memory import retrieve

        if not _semantic_enabled() or retrieve.backend() == "gcs":
            return [], ""
        from common.memory.graph_index import graph_grounded
        from common.memory.pg import build_store
        from common.memory.pg.embed import aembed_query, embed_configured

        store = build_store()
        if store is None or not embed_configured():
            return [], ""
        self_id = normalize_seed(seed)
        graph, _ = bank.load_index()
        anchors = _neighbors(graph, self_id)
        if not anchors:
            return [], ""
        q_embed = await aembed_query(terms) if terms else None
        rows = await store.search(q_text=terms, q_embed=q_embed,
                                  types=list(_FETCHABLE_TYPES), k=max_seeds * 4)
        out: list[str] = []
        for r in rows:
            nid = r.get("id", "")
            if (nid and nid != self_id and nid not in exclude and nid.startswith(_FETCHABLE)
                    and graph_grounded(graph, nid, anchors)):
                out.append(nid)
                if len(out) >= max_seeds:
                    break
        return out, (_render_semantic(out) if out else "")
    except Exception as exc:  # noqa: BLE001 — semantic seed must never break gather
        log.warning("semantic self-seed skipped for %s (%s)", seed, exc)
        return [], ""
