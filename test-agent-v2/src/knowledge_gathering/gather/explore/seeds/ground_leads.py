"""Tier-3b GROUNDING GATE (roadmap G4) — turn speculative external-LLM leads into REAL seeds, NO LLM."""

from __future__ import annotations

import asyncio

from common.memory.graph_index import match_index_nodes
from knowledge_gathering.gather.explore.seeds.atlassian_search import atlassian_search_seeds
from knowledge_gathering.gather.explore.seeds.self_seed import _FETCHABLE
from knowledge_gathering.monitoring import get_logger

log = get_logger("explore.ground_leads")


def _memory_ids(graph, lead: str) -> list[str]:
    """Fetchable jira:/confluence: node ids in the memory index matching `lead` (G0's predicate)."""
    return [
        nid for n in match_index_nodes(graph, lead)
        if (nid := n.get("id", "")).startswith(_FETCHABLE)
    ]


def _render(grounded_seeds: list[str], unconfirmed: list[str]) -> str:
    """Compact block for the gather reply: grounded ids, then unconfirmed phrases (never seeds)."""
    lines = [f"External-LLM leads — grounded {len(grounded_seeds)}, unconfirmed {len(unconfirmed)}:",
             *[f"- {sid}" for sid in grounded_seeds]]
    if unconfirmed:
        lines += ["Unconfirmed leads (not searched into the pack; chase manually):",
                  *[f"- {lead}" for lead in unconfirmed]]
    return "\n".join(lines)


async def ground_leads(
    client,
    bank,
    leads: list[str],
    *,
    project: str | None,
    exclude: set[str],
    max_seeds: int = 5,
    max_searches: int = 4,
) -> tuple[list[str], list[str], str]:
    """Ground external-LLM `leads` → `(grounded_seeds, unconfirmed_leads, note_md)`."""
    try:
        clean: list[str] = []
        for lead in leads or []:
            s = (lead or "").strip()
            if s and s not in clean:
                clean.append(s)
        if not clean:
            return [], [], ""

        try:
            graph, _ = await asyncio.to_thread(bank.load_index)  # blocking GCS read off the event loop
        except Exception as exc:  # noqa: BLE001 — no index → memory grounding is simply empty
            log.warning("ground_leads: index load failed (%s); memory grounding disabled", exc)
            graph = None

        grounded: set[str] = set()
        unconfirmed: list[str] = []
        searches_used = 0

        for lead in clean:
            ids = _memory_ids(graph, lead) if graph is not None else []
            if ids:
                grounded.update(i for i in ids if i not in exclude)
                continue
            if searches_used < max_searches:
                searches_used += 1
                seeds, _ = await atlassian_search_seeds(
                    client, lead, project=project, max_seeds=max_seeds, exclude=exclude)
                if seeds:
                    grounded.update(seeds)
                    continue
            unconfirmed.append(lead)

        grounded_seeds = sorted(i for i in grounded if i not in exclude)[:max_seeds]
        return grounded_seeds, unconfirmed, _render(grounded_seeds, unconfirmed)
    except Exception as exc:  # noqa: BLE001 — the grounding gate must never break gather
        log.warning("ground_leads skipped (%s)", exc)
        return [], [], ""
