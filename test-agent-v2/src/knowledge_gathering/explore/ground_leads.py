"""Tier-3b GROUNDING GATE (roadmap G4) — turn speculative external-LLM leads into REAL seeds, NO LLM.

The external LLM (`explore.ask_llm`) is a lead generator, never a source of truth. This gate keeps
a lead ONLY if it resolves to a real fetchable source — a memory node (`match_index_nodes`) or an
Atlassian hit (`atlassian_search_seeds`). Grounded leads become `extra_seeds`; the rest are
"unconfirmed" — surfaced to the human, NEVER promoted or written into the pack as fact (§3.4). This
keeps hallucinated requirements out of the test basis. No LLM call; any error → `([], [], "")`.
"""

from __future__ import annotations

from knowledge_gathering.explore.atlassian_search import atlassian_search_seeds
from knowledge_gathering.explore.index import match_index_nodes
from knowledge_gathering.explore.self_seed import _FETCHABLE  # ("jira:", "confluence:")
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
    lines = [
        f"External-LLM leads — grounded {len(grounded_seeds)}, unconfirmed {len(unconfirmed)}:"
    ]
    lines += [f"- {sid}" for sid in grounded_seeds]
    if unconfirmed:
        lines.append("Unconfirmed leads (not searched into the pack; chase manually):")
        lines += [f"- {lead}" for lead in unconfirmed]
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
    """Ground external-LLM `leads` → `(grounded_seeds, unconfirmed_leads, note_md)`.

    Each lead is grounded against MEMORY (`match_index_nodes`), then on a miss (within the
    `max_searches` budget) against ATLASSIAN (`atlassian_search_seeds`). GROUNDED if it resolves to
    >=1 fetchable id, else UNCONFIRMED (surfaced in `note_md`, never a seed). `grounded_seeds` is
    deduped, exclude-filtered, stable-sorted, capped at `max_seeds`. NEVER raises → `([], [], "")`."""
    try:
        # Dedup leads (preserve first occurrence / original phrasing); drop blanks.
        clean: list[str] = []
        for lead in leads or []:
            s = (lead or "").strip()
            if s and s not in clean:
                clean.append(s)
        if not clean:
            return [], [], ""

        try:
            graph, _ = bank.load_index()
        except Exception as exc:  # noqa: BLE001 — no index → memory grounding is simply empty
            log.warning("ground_leads: index load failed (%s); memory grounding disabled", exc)
            graph = None

        grounded: set[str] = set()
        unconfirmed: list[str] = []
        searches_used = 0

        for lead in clean:
            ids = _memory_ids(graph, lead) if graph is not None else []
            if ids:  # resolved to a real memory node → grounded (add the NEW, non-excluded ids)
                grounded.update(i for i in ids if i not in exclude)
                continue
            if searches_used < max_searches:  # memory miss → ground against Atlassian (budgeted)
                searches_used += 1
                seeds, _ = await atlassian_search_seeds(
                    client, lead, project=project, max_seeds=max_seeds, exclude=exclude)
                if seeds:  # resolved to a real Atlassian hit → grounded
                    grounded.update(seeds)
                    continue
            unconfirmed.append(lead)  # nothing resolved (or budget spent) → unconfirmed, NOT a seed

        # dedup (set) + drop excluded + stable sort + cap — mirrors G0/G1's seed shaping.
        grounded_seeds = sorted(i for i in grounded if i not in exclude)[:max_seeds]
        return grounded_seeds, unconfirmed, _render(grounded_seeds, unconfirmed)
    except Exception as exc:  # noqa: BLE001 — the grounding gate must never break gather
        log.warning("ground_leads skipped (%s)", exc)
        return [], [], ""
