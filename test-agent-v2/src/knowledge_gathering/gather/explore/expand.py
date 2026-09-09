"""The single pre-crawl fan-out (G2 → G0 → G1 → G4) — the reusable expansion round."""

from __future__ import annotations

from knowledge_gathering.gather.crawl.seed import normalize_seed
from knowledge_gathering.gather.explore.seeds.atlassian_search import atlassian_search_seeds
from knowledge_gathering.gather.explore.seeds.ground_leads import ground_leads
from knowledge_gathering.gather.explore.seeds.self_seed import memory_self_seed, semantic_self_seed
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
    parent: str | None = None,
    exclude: set[str] | None = None,
    leads: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Run ONE pre-crawl fan-out (B1 → G0 → G1 → G4-grounding) and return `(new_seeds, md_blocks)`."""
    exclude = set(exclude or ())
    seed_norm = normalize_seed(seed)
    new_seeds: list[str] = []
    climb_md = prior_md = sem_md = search_md = leads_md = ""
    focus = terms

    def _add(candidates: list[str]) -> None:
        for s in candidates:
            if s not in new_seeds and s not in exclude:
                new_seeds.append(s)

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
        sem_seeds, sem_md = await semantic_self_seed(bank, seed, focus, exclude=exclude | set(new_seeds) | {seed_norm})
        _add(sem_seeds)

    if thin and focus:
        search_seeds, search_md = await atlassian_search_seeds(client, focus, project=project, exclude=exclude | set(new_seeds) | {seed_norm})
        _add(search_seeds)
        log.info("A2A gather: thin seed=%s → atlassian search promoted %d seed(s): %s", seed, len(search_seeds), search_seeds)

    if leads:
        grounded, unconfirmed, leads_md = await ground_leads(client, bank, leads, project=project, exclude=exclude | set(new_seeds) | {seed_norm})
        _add(grounded)
        log.info("A2A gather: seed=%s → external-LLM leads grounded=%d unconfirmed=%d", seed, len(grounded), len(unconfirmed))

    md_blocks = [md for md in (climb_md, prior_md, sem_md, search_md, leads_md) if md]
    return new_seeds, md_blocks
