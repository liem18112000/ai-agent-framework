"""The single pre-crawl fan-out (G2 → G0 → G1 → G4) — the reusable expansion round.

`expansion_round` is the ONE place the tier wiring lives, shared by the single-pass gather
(`executor.gather`) and the G5 explore loop (`explore.loop`) so there is no copy-paste. It
imports the tiers from sibling `explore.*` modules and calls no crawl itself.
"""

from __future__ import annotations

import asyncio

from knowledge_gathering.explore.ask_llm import ask_llm_leads, leads_enabled
from knowledge_gathering.explore.atlassian_search import atlassian_search_seeds
from knowledge_gathering.explore.ground_leads import ground_leads
from knowledge_gathering.explore.hypothesize import hypothesize_enabled, hypothesize_terms
from knowledge_gathering.explore.self_seed import memory_self_seed
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
    """Run ONE pre-crawl fan-out (G2 → B1 → G0 → G1 → G4) and return `(new_seeds, md_blocks)`.

    The single reusable expansion both the single-pass gather and the G5 loop call (no copy-paste).
    `exclude` holds already-promoted/visited ids; `new_seeds` are freshly promoted jira:/confluence:
    ids in tier order; `md_blocks` are the reply notes in the same fixed order (empties dropped).

    `allow_hypothesize`/`allow_leads` gate the two OPTIONAL LLM tiers (G2/G4): each is flag-gated
    AND `asyncio.to_thread`-offloaded — a blocking Vertex call on the event loop has killed the
    Cloud Run instance (ERROR_TIMEOUT). The core G0+G1 fan-out makes NO LLM call. Each tier is
    best-effort ([]/""), so this never raises the tiers' own errors."""
    exclude = set(exclude or ())
    seed_norm = normalize_seed(seed)
    new_seeds: list[str] = []
    hyp_md = climb_md = prior_md = search_md = leads_md = ""
    focus = terms

    def _add(candidates: list[str]) -> None:  # dedup vs the running new_seeds + the exclude set
        for s in candidates:
            if s not in new_seeds and s not in exclude:
                new_seeds.append(s)

    # G2 — hypothesize: ONE thread-offloaded LLM call turns the seed's title/description/labels
    # into FOCUSED terms that REPLACE the raw title-substring terms feeding G0/G1. Best-effort:
    # "" → keep raw terms. Re-checks the flag so a disabled gather makes zero LLM calls.
    if allow_hypothesize and hypothesize_enabled() and title:
        hyp = await asyncio.to_thread(hypothesize_terms, title, description, labels)
        if hyp:
            log.info("A2A gather: hypothesize enriched terms for %s: %r", seed, hyp)
            focus, hyp_md = hyp, f"Hypothesized focus: {hyp}"

    # B1 — structural climb (thin seeds only): BEFORE memory recall, promote the seed's parent
    # (the epic/story carrying the real AC). A thin container has no gravity, so G0 would pull in
    # the dominant bank domain; climbing anchors the pack on the real spec instead (the crawl then
    # reaches the epic + siblings via the parent's links). Pure structural — no LLM, no memory.
    climbed = False
    if thin and parent:
        parent_norm = normalize_seed(parent)
        if parent_norm not in exclude and parent_norm != seed_norm:
            _add([parent_norm])
            climb_md = f"Thin seed — climbed to structural parent {parent}"
            climbed = True
            log.info("A2A gather: thin seed=%s → climbed to parent %s", seed, parent)

    # G0 — memory self-seed: consult the knowledge index and promote prior jira/confluence nodes.
    # Pure memory-read. SKIPPED when a thin seed climbed to a parent (B1: let the spec drive, not
    # the memory well); a thin orphan with no parent still falls back to recall so it's never blank.
    if not climbed:
        prior_seeds, prior_md = memory_self_seed(bank, seed, focus)
        _add(prior_seeds)

    # G1 — Atlassian search: only when the seed is THIN, sweep Jira/Confluence over the focus terms
    # and promote hits to seeds (the crawl then processes them under the existing budget/dedup).
    if thin and focus:
        search_seeds, search_md = await atlassian_search_seeds(
            client, focus, project=project, exclude=exclude | set(new_seeds) | {seed_norm})
        _add(search_seeds)
        log.info("A2A gather: thin seed=%s → atlassian search promoted %d seed(s): %s",
                 seed, len(search_seeds), search_seeds)

    # G4 — external-LLM leads (opt-in, default OFF). ONE thread-offloaded LLM call enumerates
    # likely-related concepts from WORLD knowledge (things NOT in the ticket — unlike G2). Each is
    # speculative, so a GROUNDING GATE keeps it only if it resolves to a real memory/Atlassian hit:
    # grounded → seeds; unconfirmed → surfaced to the human, NEVER promoted or written as fact.
    if allow_leads and leads_enabled() and title:
        leads = await asyncio.to_thread(ask_llm_leads, title, description, labels)
        grounded, unconfirmed, leads_md = await ground_leads(
            client, bank, leads, project=project,
            exclude=exclude | set(new_seeds) | {seed_norm})
        _add(grounded)
        log.info("A2A gather: seed=%s → external-LLM leads grounded=%d unconfirmed=%d",
                 seed, len(grounded), len(unconfirmed))

    md_blocks = [md for md in (hyp_md, climb_md, prior_md, search_md, leads_md) if md]
    return new_seeds, md_blocks
