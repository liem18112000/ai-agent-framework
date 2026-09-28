"""Tier-5 cloud discover (roadmap X2) — enumerate the prominent live services across every provider
and env, NO LLM. Provider-neutral: the reach is the swappable `CloudProvider` port; ranking, capping,
and the grounding-gated re-rank stay here in the shared layer.

A seed producer in the shape of `atlassian_search_seeds`: returns `(extra_seeds, note_md)` of canonical
`cloudsvc:<provider>/<env>/<platform>/<name>` ids, ranked by term-match ∪ liveness ∪ env-weight and
capped (no silent truncation)."""

from __future__ import annotations

import asyncio

from common.cloud import ServiceRef, cloud_providers
from knowledge_gathering.gather.explore.planners.schemas import CloudExplorePlan
from knowledge_gathering.gather.explore.seeds.self_seed import salient_tokens
from knowledge_gathering.monitoring import get_logger

log = get_logger("explore.cloud_discover")

# prod is "closest to reality"; dev the noisiest. Weight nudges ranking, never gates discovery.
_ENV_WEIGHT = {"prod": 1.0, "test": 0.8, "performance": 0.6, "dev-staging": 0.4, "dev": 0.2}
_W_TERM, _W_LIVE, _W_ENV = 0.6, 0.2, 0.2

# Patchable seam for tests: a test injects a {name: FakeCloudProvider} registry here.
_providers = cloud_providers


def _haystack(ref: ServiceRef) -> str:
    """Match text for a service — name + resource path + labels, lowercased."""
    return " ".join([ref.name, ref.resource_path, *(getattr(ref, "labels", None) or [])]).lower()


def _term_match(ref: ServiceRef, tokens: list[str]) -> float:
    """Fraction of ticket tokens appearing in the service haystack (0..1). No tokens → neutral 0.5."""
    if not tokens:
        return 0.5
    hay = _haystack(ref)
    return sum(t in hay for t in tokens) / len(tokens)


def _relevant(ref: ServiceRef, tokens: list[str], hints: list[str]) -> bool:
    """A service is promotable ONLY if it actually matches the ticket — at least one salient ticket
    token in its haystack, or an LLM priority hint on its name. Without this gate, a ticket whose terms
    match NO service name collapses the ranking to liveness+env-weight and the cap fills with arbitrary
    live services (the cloud-discover noise). No relevance signal → promote nothing."""
    hay = _haystack(ref)
    if any(tok in hay for tok in tokens):
        return True
    name = ref.name.lower()
    return any(h and (h in name or name in h) for h in hints)


def _score(ref: ServiceRef, tokens: list[str]) -> float:
    return (_W_TERM * _term_match(ref, tokens)
            + _W_LIVE * ref.live
            + _W_ENV * _ENV_WEIGHT.get(ref.env, 0.2))


def _rank(refs: list[ServiceRef], terms: str) -> list[ServiceRef]:
    """Deterministic numeric rank (desc), tie-broken by node_id for stable output."""
    tokens = salient_tokens(terms)
    return sorted(refs, key=lambda r: (-_score(r, tokens), r.node_id))


def rerank_with_plan(plan: CloudExplorePlan, ranked: list[ServiceRef]) -> list[ServiceRef]:
    """X5 grounding gate: reorder `ranked` so services whose name matches an LLM priority hint come
    first (in hint order); everything else keeps its numeric order. Never adds/removes a candidate —
    the LLM can only reprioritise what discovery actually returned."""
    hints = plan.hints()
    if not hints:
        return ranked

    def rank_key(r: ServiceRef) -> int:
        name = r.name.lower()
        for i, h in enumerate(hints):
            if h and (h in name or name in h):
                return i
        return len(hints)

    return sorted(ranked, key=rank_key)  # stable: preserves numeric order within a priority bucket


def _discover_all() -> list[ServiceRef]:
    """Iterate every configured provider × its envs, merging ServiceRefs. One provider/env failing
    must not kill the rest (tier-2 rule). SYNC — the caller offloads it to a thread."""
    out: list[ServiceRef] = []
    for name, provider in _providers().items():
        if not provider.is_configured():
            continue
        for env_key in provider.env_keys():
            try:
                out += provider.discover(env_key)
            except Exception as exc:  # noqa: BLE001 — one provider/env failing must not kill the rest
                log.warning("cloud discover failed for %s/%s (%s)", name, env_key, exc)
    return out


def _render(kept: list[ServiceRef], total: int, cap: int) -> str:
    lines = [f"Cloud discover — {total} live service(s) found; promoting top {len(kept)}:",
             *[f"- {r.node_id}" + (f"  [{r.resource_path}]" if r.resource_path else "") for r in kept]]
    if total > len(kept):
        lines.append(f"- … capped at {cap} of {total} (raise KGA_CLOUD_MAX_SERVICES to promote more)")
    return "\n".join(lines)


async def cloud_service_seeds(
    terms: str,
    *,
    exclude: set[str] | None = None,
    cloud_max_services: int = 8,
    plan: CloudExplorePlan | None = None,
) -> tuple[list[str], str]:
    """Return `(extra_seeds, note_md)` — ranked, capped `cloudsvc:` ids across every configured provider.

    `plan` (optional, from the X5 sub-agent) grounds-gated re-ranks the candidates; absent → numeric
    rank only. Degrades to `([], "")` when no provider is configured or any step fails."""
    try:
        refs = await asyncio.to_thread(_discover_all)
        if not refs:
            return [], ""
        # RELEVANCE GATE: keep only services that actually match the ticket (or an LLM hint) BEFORE
        # ranking/capping — so the cap promotes useful services instead of filling with arbitrary live
        # ones when the ticket terms match nothing (the cloud-discover noise the user hit).
        tokens = salient_tokens(terms)
        hints = plan.hints() if plan is not None else []
        relevant = [r for r in refs if _relevant(r, tokens, hints)]
        if not relevant:
            log.info("cloud discover: %d live service(s), none matched the ticket — promoting none", len(refs))
            return [], (f"Cloud discover — scanned {len(refs)} live service(s); none matched the ticket "
                        "(no cloud service promoted — refine the ticket terms to surface relevant ones).")
        ranked = _rank(relevant, terms)
        if plan is not None:
            ranked = rerank_with_plan(plan, ranked)
        # G5: optional JEV Score re-rank before the cap — a no-op unless the source gate is on AND a
        # decision backend is configured (offloaded; JEV Score is blocking). Default → numeric/plan rank.
        from knowledge_gathering.gather.explore.source_gate import score_rank
        ranked = await asyncio.to_thread(score_rank, ranked, state=terms, describe=lambda r: r.node_id)
        exclude = exclude or set()
        seeds: list[str] = []
        kept: list[ServiceRef] = []
        for r in ranked:
            if r.node_id in exclude or r.node_id in seeds:
                continue
            seeds.append(r.node_id)
            kept.append(r)
            if len(seeds) >= cloud_max_services:
                break
        if len(ranked) > len(kept):
            log.info("cloud discover: capped %d of %d services (max=%d)", len(kept), len(ranked), cloud_max_services)
        return (seeds, _render(kept, len(ranked), cloud_max_services)) if seeds else ([], "")
    except Exception as exc:  # noqa: BLE001 — discover must never break gather
        log.warning("cloud discover skipped (%s)", exc)
        return [], ""
