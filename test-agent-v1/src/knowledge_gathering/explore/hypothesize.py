"""Tier-1/2 hypothesize step (roadmap G2) — ONE bounded LLM call → focused search terms.

Turns the seed's title/description/labels into a compact set of SEARCHABLE concepts (key phrases
/ entities / subsystems) that REPLACE the raw title-substring terms feeding G0 self-seed + G1
search — the raw terms over-match (a broad token like "import" hits half the index).

Discipline:
- Flag-gated, default OFF (`KGA_LLM_HYPOTHESIZE`). When off, ZERO LLM calls (caller skips the
  thread offload).
- Best-effort: disabled / empty title / Vertex unconfigured / error / junk → `""` (caller keeps
  the raw probe terms). Never breaks gather.
- QUERY TERMS ONLY — never turned into ticket ids / URLs / seeds; grounded downstream by G0/G1.
- The single Vertex call is BLOCKING by design so the async caller offloads it with
  `asyncio.to_thread` — a blocking Vertex call on the event loop starves Cloud Run's liveness
  probe and kills the instance (ERROR_TIMEOUT).
"""

from __future__ import annotations

import json
import os

from common.llm.vertex import complete, vertex_config
from knowledge_gathering.monitoring import get_logger

log = get_logger("explore.hypothesize")

_FLAG = "KGA_LLM_HYPOTHESIZE"
_MAX_TOKENS = 400  # short JSON object of terms — bounds the single call
_DESC_CAP = 1000  # cap the (possibly long) ticket body fed to the prompt
_FIELDS = ("key_phrases", "entities", "subsystems")
_MAX_TERMS = 8  # cap the flattened list — G0/G1 match per token substring, so MORE terms BROADEN
# (over-match) instead of tightening. A few distinctive terms, whatever the model returns.


def hypothesize_enabled() -> bool:
    """G2 opt-in (default OFF). Exposed so the async caller can skip the thread offload entirely
    when disabled, not just rely on `hypothesize_terms` short-circuiting."""
    return os.environ.get(_FLAG, "").lower() in ("1", "true", "yes", "on")


def _prompt(title: str, description: str, labels: list[str]) -> str:
    """Prompt for a FEW distinctive search terms as strict JSON — no ids/URLs. Demands rare/precise
    terms and bans broad words: G0/G1 match per token substring, so an exhaustive list broadens
    the match instead of tightening it."""
    lbls = ", ".join(labels) if labels else "(none)"
    return (
        "You are the QA Testing Agent's search-planning step. Given a ticket's title, short "
        "description, and labels, return the MOST distinctive, specific search terms to find "
        "related work in Jira/Confluence and the codebase — key phrases, domain entities, and "
        "subsystem/component names.\n"
        "Return at most ~6 of the MOST distinctive, specific search terms. Prefer rare/precise "
        "terms (proper nouns, code identifiers, unique feature names) over broad generic words. "
        "AVOID generic words like: document, system, data, service, component, module, UI, "
        "frontend, styling, management, validation, mapping, structure. Keep each term 1-2 "
        "words.\n"
        'Return ONLY JSON: {"key_phrases":[...],"entities":[...],"subsystems":[...]}.\n'
        "Do NOT invent ticket ids, issue keys, or URLs — return concepts to search for, not "
        "specific tickets.\n\n"
        f"Title: {title}\n"
        f"Description: {description[:_DESC_CAP] or '(none)'}\n"
        f"Labels: {lbls}\n"
    )


def _coerce_terms(raw: str) -> list[str]:
    """Parse the LLM JSON object and flatten its three fields into a deduped, order-stable list of
    non-empty strings. Junk → `[]`. Tolerates a ```json fence and a scalar-instead-of-list field."""
    text = raw.strip()
    if text.startswith("```"):  # strip a ```json fence if the model added one
        text = text.split("```", 2)[1].removeprefix("json").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict):
        return []
    out: list[str] = []
    for field in _FIELDS:
        v = data.get(field)
        if v is None:  # missing field — don't let str(None) become "None"
            continue
        items = v if isinstance(v, list) else [v]  # coerce a scalar field to a 1-elem list
        for item in items:
            s = "" if item is None else str(item).strip()
            if s and s not in out:
                out.append(s)
    return out


def hypothesize_terms(title: str, description: str = "", labels: list[str] | None = None) -> str:
    """ONE blocking Claude-on-Vertex call → a space-joined string of focused search terms, to drop
    into `memory_self_seed` (G0) / `atlassian_search_seeds` (G1) in place of the raw terms.

    Returns `""` (caller keeps the raw probe terms) when the flag is OFF, `title` is empty, Vertex
    is unconfigured, or anything fails. BLOCKING by design — offloaded via `asyncio.to_thread`.
    At most ONE LLM call; never raises."""
    if not hypothesize_enabled() or not title.strip():
        return ""
    try:
        cfg = vertex_config()
        if not cfg:  # flag on but no Vertex → keep raw terms
            return ""
        proj, loc, model = cfg
        raw = complete(
            _prompt(title.strip(), (description or "").strip(), labels or []),
            project=proj, location=loc, model=model, max_tokens=_MAX_TOKENS,
        )
        terms = _coerce_terms(raw)[:_MAX_TERMS]  # cap the flattened list
        if not terms:
            log.info("hypothesize: LLM returned no usable terms; keeping raw probe terms")
            return ""
        joined = " ".join(terms)
        log.info("hypothesize: %d focus term(s) → %r", len(terms), joined)
        return joined
    except Exception as exc:  # noqa: BLE001 — best-effort; G2 must never break gather
        log.warning("hypothesize skipped (%s)", exc)
        return ""
