"""Tier-1 memory self-seed (roadmap G0) — pure memory-read, NO LLM.

Before the crawl, query the GCS knowledge index for PRIOR nodes (and INSIGHT-type insights)
matching the seed's terms, promote fetchable jira:/confluence: hits to `extra_seeds`, and
surface the rest as a "Prior knowledge from memory" note. Any failure → `([], "")`; never
breaks gather, makes no LLM call.
"""

from __future__ import annotations

from common.models import INSIGHT
from knowledge_gathering.explore.index import match_index_nodes, rank_promotions
from knowledge_gathering.loop.seed import normalize_seed
from knowledge_gathering.monitoring import get_logger

log = get_logger("explore.self_seed")

# Generic tokens that would match half the index — dropped alongside anything len < 3.
_STOPWORDS = frozenset({
    "the", "and", "for", "with", "from", "this", "that", "are", "was",
    "not", "but", "all", "any", "has", "have", "its", "into", "when", "will",
})
_FETCHABLE = ("jira:", "confluence:")  # promotable + followable by the crawl


def salient_tokens(text: str) -> list[str]:
    """Distinct usable tokens of `text` — lowercased, len >= 3, non-stopword, order-preserving.
    The single filter shared by G0 self-seed and G1 Atlassian search — don't duplicate the rule."""
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
    """Return `(extra_seeds, prior_md)` from the memory index for `seed` (+ optional terms).

    `extra_seeds`: canonical jira:/confluence: ids of matching prior nodes (seed excluded),
    IDF-rarity ranked + hub-suppressed (B4), capped at `max_seeds`. `prior_md`: a "Prior knowledge
    from memory" block (insights first), or `""`. NEVER raises — any failure → ([], "").
    """
    try:
        self_id = normalize_seed(seed)
        seed_key = self_id.split(":", 1)[-1]  # bare LUZ-123 / 12345, matched as a substring
        queries = _queries(seed_key, terms)
        graph, _ = bank.load_index()
        matched: dict[str, dict] = {}
        for q in queries:
            for n in match_index_nodes(graph, q):
                nid = n.get("id", "")
                if nid and nid != self_id:  # never re-seed the seed
                    matched[nid] = n
        if not matched:
            return [], ""
        # B4 — promote by IDF rarity + hub suppression, not first-N-alphabetical, so a saturated
        # memory domain no longer floods an unrelated ticket's seeds.
        extra_seeds = rank_promotions(graph, queries, prefixes=_FETCHABLE,
                                      max_seeds=max_seeds, exclude={self_id})
        return extra_seeds, _render(matched)
    except Exception as exc:  # noqa: BLE001 — self-seed must never break gather
        log.warning("memory self-seed skipped for %s (%s)", seed, exc)
        return [], ""
