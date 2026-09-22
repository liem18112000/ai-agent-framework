"""Tier-3b external-LLM lead enumerator (roadmap G4) — ONE bounded LLM call → speculative LEADS.

Unlike G2 (`explore.hypothesize`), which distills the ticket's OWN text into search *terms*, G4
asks the LLM for LEADS from world knowledge — related features/subsystems/edge-cases NOT
necessarily stated in the ticket. These are speculative (possibly hallucinated), so they are
candidate QUERIES ONLY: the caller runs each through the GROUNDING GATE (`explore.ground_leads`)
and promotes it only if it resolves to a real source. A "lead generator, not source of truth"
(RESEARCH §3.4) — never turns a lead into a seed/note/fact itself.

Discipline (mirrors `explore.hypothesize`):
- Flag-gated, default OFF (`KGA_LLM_LEADS`). When off, ZERO LLM calls (caller skips the offload).
- Best-effort: disabled / empty title / Vertex unconfigured / error / junk → `[]`. Never breaks
  gather.
- The single Vertex call is BLOCKING by design so the async caller offloads it via
  `asyncio.to_thread` — a blocking Vertex call on the event loop starves Cloud Run's liveness
  probe (ERROR_TIMEOUT).
- Ideally a DIFFERENT model family (e.g. Gemini) than the downstream scenario generator, to avoid
  compounding one model's blind spots (§3.4). Currently reuses Claude-on-Vertex; Gemini is a TODO.
"""

from __future__ import annotations

import json
import os

from common.llm.vertex import complete, vertex_config
from knowledge_gathering.monitoring import get_logger

log = get_logger("explore.ask_llm")

_FLAG = "KGA_LLM_LEADS"
_MAX_TOKENS = 400  # short JSON array of phrases — bounds the single call
_DESC_CAP = 1000  # cap the (possibly long) ticket body fed to the prompt
_MAX_LEADS = 6  # cap the list — each lead costs a grounding search downstream, so bound the fan-out


def leads_enabled() -> bool:
    """G4 opt-in (default OFF). Exposed so the async caller can skip the thread offload entirely
    when disabled, not just rely on `ask_llm_leads` short-circuiting."""
    return os.environ.get(_FLAG, "").lower() in ("1", "true", "yes", "on")


def _prompt(title: str, description: str, labels: list[str]) -> str:
    """Prompt for speculative LEADS from world knowledge — related work ELSEWHERE, to widen the
    search. Bans inventing ticket ids/keys/URLs (ungroundable); the grounding gate resolves the
    returned phrases to real sources instead."""
    lbls = ", ".join(labels) if labels else "(none)"
    return (
        "You are the QA Testing Agent's lead-generation step. Given a ticket's title, short "
        "description, and labels, list related concepts/features/subsystems/edge-cases that "
        "likely have related work elsewhere (in Jira/Confluence/the codebase) for this ticket — "
        "things NOT necessarily stated in it, to widen the search.\n"
        "Return ONLY a JSON array of at most ~6 short search phrases (1-4 words each). Do NOT "
        "invent ticket ids, issue keys, or URLs.\n\n"
        f"Title: {title}\n"
        f"Description: {description[:_DESC_CAP] or '(none)'}\n"
        f"Labels: {lbls}\n"
    )


def _coerce_leads(raw: str) -> list[str]:
    """Parse the LLM JSON array into a deduped, order-stable list of non-empty strings. Tolerates a
    ```json fence; requires a JSON *array* (dict / scalar / non-JSON → `[]`)."""
    text = raw.strip()
    if text.startswith("```"):  # strip a ```json fence if the model added one
        text = text.split("```", 2)[1].removeprefix("json").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):  # must be a JSON array of phrases
        return []
    out: list[str] = []
    for item in data:
        s = "" if item is None else str(item).strip()
        if s and s not in out:
            out.append(s)
    return out


def ask_llm_leads(title: str, description: str = "", labels: list[str] | None = None) -> list[str]:
    """ONE blocking Claude-on-Vertex call → a list of speculative lead phrases (candidate QUERIES),
    to be run through the grounding gate downstream.

    Returns `[]` when the flag is OFF, `title` is empty, Vertex is unconfigured, or anything fails.
    BLOCKING by design — offloaded via `asyncio.to_thread`. At most ONE LLM call; never raises."""
    if not leads_enabled() or not title.strip():
        return []
    try:
        cfg = vertex_config()
        if not cfg:  # flag on but no Vertex → no leads
            return []
        proj, loc, model = cfg
        raw = complete(
            _prompt(title.strip(), (description or "").strip(), labels or []),
            project=proj, location=loc, model=model, max_tokens=_MAX_TOKENS,
        )
        leads = _coerce_leads(raw)[:_MAX_LEADS]  # cap the fan-out
        if not leads:
            log.info("ask_llm: LLM returned no usable leads")
            return []
        log.info("ask_llm: %d external lead(s): %r", len(leads), leads)
        return leads
    except Exception as exc:  # noqa: BLE001 — best-effort; G4 must never break gather
        log.warning("ask_llm leads skipped (%s)", exc)
        return []
