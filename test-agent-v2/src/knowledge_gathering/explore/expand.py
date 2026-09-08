"""The single pre-crawl fan-out (G2 → G0 → G1 → G4) — the reusable expansion round."""

from __future__ import annotations

import asyncio

from knowledge_gathering.explore.ask_llm import ask_llm_leads, leads_enabled
from knowledge_gathering.explore.atlassian_search import atlassian_search_seeds
from knowledge_gathering.explore.ground_leads import ground_leads
from knowledge_gathering.explore.hypothesize import hypothesize_enabled, hypothesize_terms
from knowledge_gathering.explore.self_seed import memory_self_seed, semantic_self_seed
from knowledge_gathering.loop.seed import normalize_seed
from knowledge_gathering.monitoring import get_logger

log = get_logger("explore.expand")


async def expansion_round(
    bank,
    client,
    *,
    seed: str,
    terms: str,
    thin: bool,
    project: str | None,
    title: str = "",
    description: str = "",
    labels: list[str] | None = None,
    parent: str | None = None,
    exclude: set[str] | None = None,
    allow_hypothesize: bool = True,
    allow_leads: bool = True,
) -> tuple[list[str], list[str]]:
    """Run ONE pre-crawl fan-out (G2 → B1 → G0 → G1 → G4) and return `(new_seeds, md_blocks)`."""
    exclude = set(exclude or ())
    seed_norm = normalize_seed(seed)
    new_seeds: list[str] = []
    hyp_md = climb_md = prior_md = sem_md = search_md = leads_md = ""
    focus = terms

    def _add(candidates: list[str]) -> None:
        for s in candidates:
            if s not in new_seeds and s not in exclude:
                new_seeds.append(s)

    if allow_hypothesize and hypothesize_enabled() and title:
        hyp = await asyncio.to_thread(hypothesize_terms, title, description, labels)
        if hyp:
            log.info("A2A gather: hypothesize enriched terms for %s: %r", seed, hyp)
            focus, hyp_md = hyp, f"Hypothesized focus: {hyp}"

    climbed = False
    if thin and parent:
        parent_norm = normalize_seed(parent)
        if parent_norm not in exclude and parent_norm != seed_norm:
            _add([parent_norm])
            climb_md = f"Thin seed — climbed to structural parent {parent}"
            climbed = True
            log.info("A2A gather: thin seed=%s → climbed to parent %s", seed, parent)

    if not climbed:
        prior_seeds, prior_md = memory_self_seed(bank, seed, focus)
        _add(prior_seeds)
        sem_seeds, sem_md = await semantic_self_seed(
            bank, seed, focus, exclude=exclude | set(new_seeds) | {seed_norm})
        _add(sem_seeds)

    if thin and focus:
        search_seeds, search_md = await atlassian_search_seeds(
            client, focus, project=project, exclude=exclude | set(new_seeds) | {seed_norm})
        _add(search_seeds)
        log.info("A2A gather: thin seed=%s → atlassian search promoted %d seed(s): %s",
                 seed, len(search_seeds), search_seeds)

    if allow_leads and leads_enabled() and title:
        leads = await asyncio.to_thread(ask_llm_leads, title, description, labels)
        grounded, unconfirmed, leads_md = await ground_leads(
            client, bank, leads, project=project,
            exclude=exclude | set(new_seeds) | {seed_norm})
        _add(grounded)
        log.info("A2A gather: seed=%s → external-LLM leads grounded=%d unconfirmed=%d",
                 seed, len(grounded), len(unconfirmed))

    md_blocks = [md for md in (hyp_md, climb_md, prior_md, sem_md, search_md, leads_md) if md]
    return new_seeds, md_blocks
