"""Tier-2 Atlassian search (roadmap G1) — pre-crawl expansion for THIN seeds, NO LLM."""

from __future__ import annotations

from knowledge_gathering.explore.self_seed import salient_tokens
from knowledge_gathering.monitoring import get_logger

log = get_logger("explore.atlassian_search")


def _escape(s: str) -> str:
    r"""Escape a string for embedding inside a double-quoted JQL/CQL literal (\ before ")."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _render(seeds: list[str]) -> str:
    lines = [f"Atlassian search (seed was thin) surfaced {len(seeds)} related item(s):"]
    lines += [f"- {sid}" for sid in seeds]
    return "\n".join(lines)


async def atlassian_search_seeds(
    client,
    terms: str,
    *,
    project: str | None = None,
    max_seeds: int = 5,
    exclude: set[str] | None = None,
) -> tuple[list[str], str]:
    """Return `(extra_seeds, note_md)` — canonical jira:/confluence: ids for work related to"""
    try:
        tokens = salient_tokens(terms)
        if not tokens:
            return [], ""
        query = _escape(" ".join(tokens))
        exclude = exclude or set()

        text_clause = f'text ~ "{query}"'
        jql = (
            f'project = "{_escape(project)}" AND {text_clause} ORDER BY updated DESC'
            if project else f"{text_clause} ORDER BY updated DESC"
        )
        cql = f'{text_clause} AND type = page'

        found: list[str] = []
        try:
            found += [f"jira:{k}" for k in await client.search_jql(jql)]
        except Exception as exc:  # noqa: BLE001 — one tier failing must not kill the other
            log.warning("JQL search failed (%s): %s", jql, exc)
        try:
            found += [f"confluence:{cid}" for cid in await client.search_cql(cql)]
        except Exception as exc:  # noqa: BLE001 — e.g. no Confluence permission
            log.warning("CQL search failed (%s): %s", cql, exc)

        seeds = sorted({sid for sid in found if sid not in exclude})[:max_seeds]
        return (seeds, _render(seeds)) if seeds else ([], "")
    except Exception as exc:  # noqa: BLE001 — G1 must never break gather
        log.warning("atlassian search skipped (%s)", exc)
        return [], ""
