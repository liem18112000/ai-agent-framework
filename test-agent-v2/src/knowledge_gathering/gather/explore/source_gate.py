"""JEV source-activation gate (G3) — reuse the `DecisionProvider` cascade as a source SELECTOR.

Default OFF: a no-op that fires every eligible source = today's behaviour, unless BOTH the KGA gate
flag (`KGA_SOURCE_GATE`) is on AND a decision backend is configured (`TPD_DECISION_BACKEND`, e.g.
`jev`). When on, one `noul` per candidate answers "will this source surface in-scope knowledge for
this ticket?"; a source is dropped ONLY when JEV is both confident and below the run bar — the exact
JEV cascade (front, never replace), reused as a selector rather than a suite scorer.

UNCALIBRATED until G4 fits `KGA_SOURCE_GATE_TAU` against the KGA goldens (relevant_node_ids); keep OFF
in prod until skip-precision ≥ target with recall intact. The default `conf_min` mirrors the JEV J4
finding that the accept-side has no safe τ below ~0.40 — this gate asks an accept-type question ("will
it help?"), the exact side JEV calibrated weakly, so the bar starts high and never trusts a low-conf
skip.
"""

from __future__ import annotations

import os

from common.adk.providers import Verdict, get_decision_provider
from common.env import env_float
from knowledge_gathering.monitoring import get_logger

log = get_logger("explore.source_gate")

_DEFAULT_CONF_MIN = 0.40  # JEV J4: no safe accept-side τ below ~0.40 — never trust a lower-conf skip
_DEFAULT_TAU = 0.50       # P(source helps) run bar; SKIP only when confident AND below this

_STATEMENTS = {
    "semantic": "Prior stored knowledge (semantic memory) will surface in-scope context for this ticket.",
    "atlassian_search": "An Atlassian JQL/CQL search will surface issues or pages in scope for this ticket.",
    "ground_leads": "The external leads will ground to real in-scope Atlassian/web sources for this ticket.",
    "cloud_discover": "Live cloud-service discovery will surface services in scope for this ticket.",
}


def gate_enabled() -> bool:
    return os.environ.get("KGA_SOURCE_GATE", "").strip().lower() in ("1", "true", "yes", "on")




def _statement(key: str) -> str:
    return _STATEMENTS.get(key, f"Source {key!r} will surface in-scope knowledge for this ticket.")


def _p_true(v: Verdict) -> float:
    """P(statement holds). Prefer the distribution's truthy mass; fall back to the boolean value."""
    if v.probs:
        for k, val in v.probs.items():
            if str(k).strip().lower() in ("true", "yes", "1"):
                return float(val)
    return 1.0 if v.value else 0.0


def apply_cascade(candidates, *, state: str, provider, conf_min: float, tau: float) -> set:
    """Pure cascade: FIRE unless JEV is confident (``conf >= conf_min``) AND below the bar (``P < tau``).
    Any gate error → FIRE (a selector failure must never remove a source on its own account)."""
    fired: set = set()
    for key in candidates:
        try:
            v = provider.noul(state, _statement(key))
            p = _p_true(v)
        except Exception as exc:  # noqa: BLE001 — a gate failure must never drop a source
            log.warning("source gate: noul(%s) failed (%s) → firing", key, exc)
            fired.add(key)
            continue
        if v.confidence >= conf_min and p < tau:
            log.info("source gate SKIP %s (P=%.2f conf=%.2f < bar tau=%.2f)", key, p, v.confidence, tau)
            continue  # the ONLY skip
        fired.add(key)
    return fired


_SCORE_LEVELS = ["irrelevant", "marginal", "relevant", "central"]  # ordinal scale for JEV Score


def score_rank(items, *, state: str, describe, provider=None):
    """Re-order ``items`` best-first by a JEV ``Score`` of each item's relevance to ``state`` (G5 —
    rank the capped sources, not just yes/no). No-op (returns ``items`` unchanged) unless the gate is ON
    and a decision backend is configured, so the default numeric/plan rank is preserved. BLOCKING (JEV
    Score is sync) — call via ``asyncio.to_thread`` from the event loop. Best-effort: ANY score failure
    keeps the incoming order untouched (never partially reorder on incomplete data → never drop a
    relevant item below the cap by accident)."""
    items = list(items)
    if not items or not gate_enabled():
        return items
    provider = provider or get_decision_provider()
    if provider is None or not provider.is_configured():
        return items
    scored: list[tuple[float, object]] = []
    for item in items:
        try:
            v = provider.score(state, f"Relevance of {describe(item)} to this ticket.", _SCORE_LEVELS)
            scored.append((float(v.value), item))
        except Exception as exc:  # noqa: BLE001 — any failure → keep the numeric rank, reorder nothing
            log.warning("source gate: score(%s) failed (%s) → keeping incoming rank", describe(item), exc)
            return items
    return [item for _s, item in sorted(scored, key=lambda t: t[0], reverse=True)]  # stable: ties keep order


def select_sources(candidates, *, state: str) -> set:
    """Fire every candidate unless the gate is ON, a decision backend is configured, and the cascade is
    confident a source won't pay. Strictly additive — off by default → returns the input set unchanged."""
    candidates = set(candidates)
    if not candidates or not gate_enabled():
        return candidates
    provider = get_decision_provider()
    if provider is None or not provider.is_configured():
        return candidates  # backend OFF/unconfigured → fire all (worst case = today)
    return apply_cascade(candidates, state=state, provider=provider,
                         conf_min=env_float("KGA_SOURCE_GATE_CONF_MIN", _DEFAULT_CONF_MIN),
                         tau=env_float("KGA_SOURCE_GATE_TAU", _DEFAULT_TAU))
