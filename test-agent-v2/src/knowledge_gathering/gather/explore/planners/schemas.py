"""Structured output contracts for the explore planner `LlmAgent`s (roadmap G2 / G4)."""

from __future__ import annotations

from pydantic import BaseModel, Field

_MAX_TERMS = 8
_MAX_LEADS = 6

PLAN_INPUT_KEY = "kga_plan_in"


class PlanInput(BaseModel):
    """The ticket facts a planner reads from `session.state[PLAN_INPUT_KEY]` to build its prompt —
    written by the GatherAgent (`from_probe`), read back by each planner's `InstructionProvider`."""

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

    def as_terms(self, cap: int = _MAX_TERMS) -> str:
        """Flatten the three fields into a deduped, order-stable, capped space-joined string."""
        seen: list[str] = []
        for s in (*self.key_phrases, *self.entities, *self.subsystems):
            s = (s or "").strip()
            if s and s not in seen:
                seen.append(s)
        return " ".join(seen[:cap])


class Leads(BaseModel):
    """G4: speculative search phrases for related work elsewhere (no ids/URLs)."""

    phrases: list[str] = Field(default_factory=list)

    def as_leads(self, cap: int = _MAX_LEADS) -> list[str]:
        """Deduped, order-stable, capped list of non-empty lead phrases (mirrors `_coerce_leads`)."""
        out: list[str] = []
        for item in self.phrases:
            s = (item or "").strip()
            if s and s not in out:
                out.append(s)
        return out[:cap]
