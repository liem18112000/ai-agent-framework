"""Structured output contracts for the explore planner `LlmAgent`s (roadmap G2 / G4).

These are pydantic `BaseModel`s — NOT the stdlib-dataclass house style used elsewhere in
`knowledge_gathering.models` — because ADK's `LlmAgent(output_schema=...)` REQUIRES a pydantic
`BaseModel`: ADK derives the JSON schema from it, instructs the model to emit matching JSON, and
validates the reply with `model_validate_json(...).model_dump(exclude_none=True)` (see
`google.adk.utils._schema_utils.validate_schema`). A malformed reply raises `pydantic.ValidationError`,
which the driving `GatherAgent` catches to degrade to `probe.terms` / `[]` (the old best-effort
contract). The `as_terms()` / `as_leads()` helpers carry the dedup + cap logic that used to live in the
hand-rolled `_coerce_terms` / `_coerce_leads` parsers.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

_MAX_TERMS = 8   # mirrors hypothesize._MAX_TERMS
_MAX_LEADS = 6   # mirrors ask_llm._MAX_LEADS

# `session.state` key the GatherAgent seeds with {title, description, labels} before running a
# planner; the planners' `InstructionProvider`s read it to template the prompt the ADK-native way.
PLAN_INPUT_KEY = "kga_plan_in"


class Hypothesis(BaseModel):
    """G2: the most distinctive search terms — key phrases, entities, subsystems (no ids/URLs)."""

    key_phrases: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    subsystems: list[str] = Field(default_factory=list)

    def as_terms(self, cap: int = _MAX_TERMS) -> str:
        """Flatten the three fields into a deduped, order-stable, capped space-joined string.

        Mirrors the old `_coerce_terms(...)[:_MAX_TERMS]` + `" ".join(...)` behaviour exactly.
        """
        seen: list[str] = []
        for s in (*self.key_phrases, *self.entities, *self.subsystems):
            s = (s or "").strip()
            if s and s not in seen:
                seen.append(s)
        return " ".join(seen[:cap])


class Leads(BaseModel):
    """G4: speculative search phrases for related work elsewhere (no ids/URLs).

    `phrases` intentionally carries NO `max_length` constraint: the old `ask_llm_leads` TRUNCATED an
    over-long reply to `_MAX_LEADS` rather than rejecting it, and a hard schema bound would instead
    fail validation (→ degrade to `[]`) and lose every lead. `as_leads()` reproduces the old
    strip + dedup + cap.
    """

    phrases: list[str] = Field(default_factory=list)

    def as_leads(self, cap: int = _MAX_LEADS) -> list[str]:
        """Deduped, order-stable, capped list of non-empty lead phrases (mirrors `_coerce_leads`)."""
        out: list[str] = []
        for item in self.phrases:
            s = (item or "").strip()
            if s and s not in out:
                out.append(s)
        return out[:cap]
