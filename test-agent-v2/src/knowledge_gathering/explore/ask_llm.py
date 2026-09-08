"""Tier-3b external-LLM lead enumerator (roadmap G4) — ONE bounded LLM call → speculative LEADS."""

from __future__ import annotations

import json
import os

from common.llm.vertex import complete, vertex_config
from knowledge_gathering.monitoring import get_logger

log = get_logger("explore.ask_llm")

_FLAG = "KGA_LLM_LEADS"
_MAX_TOKENS = 400
_DESC_CAP = 1000
_MAX_LEADS = 6


def leads_enabled() -> bool:
    """G4 opt-in (default OFF). Exposed so the async caller can skip the thread offload entirely"""
    return os.environ.get(_FLAG, "").lower() in ("1", "true", "yes", "on")


def _prompt(title: str, description: str, labels: list[str]) -> str:
    """Prompt for speculative LEADS from world knowledge — related work ELSEWHERE, to widen the"""
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
    """Parse the LLM JSON array into a deduped, order-stable list of non-empty strings. Tolerates a"""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1].removeprefix("json").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    out: list[str] = []
    for item in data:
        s = "" if item is None else str(item).strip()
        if s and s not in out:
            out.append(s)
    return out


def ask_llm_leads(title: str, description: str = "", labels: list[str] | None = None) -> list[str]:
    """ONE blocking Claude-on-Vertex call → a list of speculative lead phrases (candidate QUERIES),"""
    if not leads_enabled() or not title.strip():
        return []
    try:
        cfg = vertex_config()
        if not cfg:
            return []
        proj, loc, model = cfg
        raw = complete(
            _prompt(title.strip(), (description or "").strip(), labels or []),
            project=proj, location=loc, model=model, max_tokens=_MAX_TOKENS,
        )
        leads = _coerce_leads(raw)[:_MAX_LEADS]
        if not leads:
            log.info("ask_llm: LLM returned no usable leads")
            return []
        log.info("ask_llm: %d external lead(s): %r", len(leads), leads)
        return leads
    except Exception as exc:  # noqa: BLE001 — best-effort; G4 must never break gather
        log.warning("ask_llm leads skipped (%s)", exc)
        return []
