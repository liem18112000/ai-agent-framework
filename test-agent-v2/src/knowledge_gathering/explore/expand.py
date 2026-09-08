"""The single pre-crawl fan-out (G2 → G0 → G1 → G4) — the reusable expansion round.

D15: the two speculative-LLM steps (G2 hypothesize, G4 lead enumeration) NO LONGER run inside this
round. The driving `GatherAgent` runs them as ADK `LlmAgent`s and passes their results in as
`terms=` (the focus, already enriched or `probe.terms`) and `leads=` (raw lead phrases). Everything
here stays deterministic: structural parent-climb (B1), memory/semantic self-seed (G0), Atlassian
search (G1), and the `ground_leads` grounding gate (G4). The `allow_hypothesize` / `allow_leads`
flags are retained ONLY for signature-compatibility with the still-unported explore-loop caller
(P4 deferred); they are no-ops on this path.
"""

from __future__ import annotations

from knowledge_gathering.explore.atlassian_search import atlassian_search_seeds
from knowledge_gathering.explore.ground_leads import ground_leads
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
    leads: list[str] | None = None,
    allow_hypothesize: bool = True,
    allow_leads: bool = True,
) -> tuple[list[str], list[str]]:
    """Run ONE pre-crawl fan-out (B1 → G0 → G1 → G4-grounding) and return `(new_seeds, md_blocks)`.

    `terms` is the focus (the caller pre-computes G2 enrichment). `leads` is the caller-supplied G4
    lead phrases (from the leads `LlmAgent`); when non-empty they are run through the deterministic
    `ground_leads` gate. `title`/`description`/`labels`/`allow_*` are accepted for caller
    compatibility but no longer drive any LLM call here.
    """
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
        sem_seeds, sem_md = await semantic_self_seed(
            bank, seed, focus, exclude=exclude | set(new_seeds) | {seed_norm})
        _add(sem_seeds)

    if thin and focus:
        search_seeds, search_md = await atlassian_search_seeds(
            client, focus, project=project, exclude=exclude | set(new_seeds) | {seed_norm})
        _add(search_seeds)
        log.info("A2A gather: thin seed=%s → atlassian search promoted %d seed(s): %s",
                 seed, len(search_seeds), search_seeds)

    if leads:
        grounded, unconfirmed, leads_md = await ground_leads(
            client, bank, leads, project=project,
            exclude=exclude | set(new_seeds) | {seed_norm})
        _add(grounded)
        log.info("A2A gather: seed=%s → external-LLM leads grounded=%d unconfirmed=%d",
                 seed, len(grounded), len(unconfirmed))

    md_blocks = [md for md in (climb_md, prior_md, sem_md, search_md, leads_md) if md]
    return new_seeds, md_blocks
