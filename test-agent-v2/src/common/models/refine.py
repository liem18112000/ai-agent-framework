"""Knowledge-Refinement data contracts (Step 2) — stdlib dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field

DECISION = "decision"
ASSUMPTION = "assumption"
GAP_SEED = "gap-seed"
LESSON = "lesson"
CORRECTION = "correction"
GOTCHA = "gotcha"
#: A lesson specifically about spending fewer tokens at UNCHANGED quality. Its own kind so the
#: admin surface can list them apart from general lessons; otherwise an ordinary lesson in every way.
TOKEN_SAVING = "token-saving"

INSIGHT = "insight"

ROUNDS = ("business", "technical", "qa")


@dataclass
class Question:
    """One clarifying question surfaced by refinement (a genuine judgement call)."""

    id: str
    round: str
    question: str
    why: str = ""
    options: list[dict] = field(default_factory=list)
    recommendation: str = ""
    depends_on: list[str] = field(default_factory=list)
    applies_to: str = ""
    status: str = "open"
    confidence: str = "low"


@dataclass
class Answer:
    """A human (or agent-self) answer to one Question."""

    question_id: str
    answered_by: str = "human"
    chosen_option: str = ""
    text: str = ""
    answered_at: str = ""
    new_seed: str | None = None


@dataclass
class Insight:
    """A distilled, provenance-carrying fact the refinement loop persists ('Collect insight')."""

    id: str
    kind: str
    context_id: str
    question_id: str
    statement: str
    answered_by: str = "human"
    confidence: str = "high"
    source_refs: list[str] = field(default_factory=list)
    created_at: str = ""
    run_id: str = ""
    rationale: str = ""
    rejected: list[str] = field(default_factory=list)
    origin_step: str = ""   # the POSITION that earned it — orders recall (R1), see learn/recall.py
    scope: str = "context"
    status: str = "active"
    # R6: `supersedes` lived here with no writer and no reader. openrig requires a successor pointer
    # on anything marked SUPERSEDED — a state we do not have: `veto_lesson` tombstones, and a
    # CORRECTION displaces an older lesson by recency (see INT-02 in learn/recall.py), not by
    # pointer. A field for a state that cannot occur is dead weight, so it is gone. Old persisted
    # JSON still carrying the key deserializes fine — `serialize._from` drops unknown keys.


@dataclass
class RefinementRun:
    """One refine-session run-log: inputs, questions, answers, insights, seeds, confidence."""

    run_id: str
    context_id: str
    seed: str = ""
    rounds: list[str] = field(default_factory=list)
    questions_raised: int = 0
    questions_answered: int = 0
    insights_written: int = 0
    new_seeds: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    understanding_confidence: str = ""
    started: str = ""
    ended: str = ""


@dataclass
class IngestResult:
    """The outcome of matching a turn's raw answers back to their questions."""

    answers: list[Answer] = field(default_factory=list)
    answered: list[Question] = field(default_factory=list)
    carried: list[Question] = field(default_factory=list)
    deferred: list[Question] = field(default_factory=list)


@dataclass
class RefineResult:
    """The final result of a refine session — understanding, insights, gaps, re-seeds."""

    understanding: str = ""
    confidence: str = ""
    insights: list[Insight] = field(default_factory=list)
    open_gaps: list[str] = field(default_factory=list)
    new_seeds: list[str] = field(default_factory=list)
    run: RefinementRun | None = None
