"""`DecisionProvider` — the sibling port to `ModelProvider` for typed System-1 decisions (JEV).

Not a chat model: JEV has no `generate_content`, so it lives BESIDE `ModelProvider`, never inside it
(forcing it through `complete()`/an ADK `LlmAgent` would be wrong). Default OFF — `TPD_DECISION_BACKEND`
unset → `get_decision_provider()` returns None and every caller keeps its existing LLM path (strictly
additive; the cascade fronts the LLM judge, it never replaces it). See docs/RESEARCH-jev-in-test-agent-v2.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class Verdict:
    """A typed decision. ``value`` is the outcome (chosen option / score float / bool); ``probs`` the
    per-outcome distribution (or None); ``confidence`` JEV's calibrated 0–1 self-estimate (the cascade
    gate — trust the fast path only above a confidence threshold)."""

    value: object
    probs: dict[str, float] | None
    confidence: float


@runtime_checkable
class DecisionProvider(Protocol):
    """Typed decision access (JEV Choice/Score/Noul) for the ADK layer — the sibling of `ModelProvider`."""

    name: str

    def is_configured(self) -> bool:
        """True when the provider's transport/credentials are set (the cascade's gate, like
        `ModelProvider.is_configured`)."""
        ...

    def choice(self, state: str, options: list[str], instructions: str) -> Verdict:
        """Pick one of ``options`` for ``state`` under ``instructions``; ``value`` is the chosen option."""
        ...

    def score(self, state: str, instructions: str, levels: list[str]) -> Verdict:
        """Grade ``state`` on the ordinal ``levels`` scale; ``value`` is a 0–1 float."""
        ...

    def noul(self, state: str, statement: str) -> Verdict:
        """Judge whether ``statement`` holds for ``state``; ``value`` is a bool, ``probs`` its distribution."""
        ...
