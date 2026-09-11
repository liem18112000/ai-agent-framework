"""Structured output contracts for the explore planner `LlmAgent`s (roadmap G2 / G4)."""

from __future__ import annotations

from pydantic import BaseModel, Field

_MAX_TERMS = 8
_MAX_LEADS = 6

PLAN_INPUT_KEY = "kga_plan_in"


def _dedupe(items, cap: int) -> list[str]:
    """Strip + drop empties + dedupe (order-stable) + cap — shared by `as_terms`/`as_leads`."""
    out: list[str] = []
    for s in items:
        s = (s or "").strip()
        if s and s not in out:
            out.append(s)
    return out[:cap]


class PlanInput(BaseModel):
    """Ticket facts a planner reads from `session.state[PLAN_INPUT_KEY]` (written via `from_probe`,
    read back by each planner's `InstructionProvider`)."""

    title: str = ""
    description: str = ""
    labels: list[str] = Field(default_factory=list)

    @classmethod
    def from_probe(cls, probe) -> PlanInput:
        """Build the planner input from a `SeedProbe` (the gather seed's single get_issue probe)."""
        return cls(title=probe.title, description=probe.description, labels=probe.labels or [])


class Hypothesis(BaseModel):
    """G2: the most distinctive search terms — key phrases, entities, subsystems (no ids/URLs)."""

    key_phrases: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    subsystems: list[str] = Field(default_factory=list)

    def as_terms(self) -> str:
        """Flatten the three fields into a deduped, order-stable, capped space-joined string."""
        return " ".join(_dedupe((*self.key_phrases, *self.entities, *self.subsystems), _MAX_TERMS))


class Leads(BaseModel):
    """G4: speculative search phrases for related work elsewhere (no ids/URLs)."""

    phrases: list[str] = Field(default_factory=list)

    def as_leads(self) -> list[str]:
        """Deduped, order-stable, capped list of non-empty lead phrases (mirrors `_coerce_leads`)."""
        return _dedupe(self.phrases, _MAX_LEADS)
