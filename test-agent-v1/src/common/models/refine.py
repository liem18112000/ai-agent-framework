"""Knowledge-Refinement data contracts (Step 2) — stdlib dataclasses.

The clarifying `Question`s a refine pass surfaces, the human/agent `Answer`s that settle
them, the provenance-carrying `Insight`s they distil into, and the `RefinementRun` run-log —
plus the two result records the refine engine returns (`IngestResult`, `RefineResult`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Insight kinds.
DECISION = "decision"
ASSUMPTION = "assumption"
CLARIFICATION = "clarification"
GAP_SEED = "gap-seed"
# Self-learning kinds (L0) — durable, cross-step lessons captured after any pipeline step.
LESSON = "lesson"           # a reusable fact/insight worth remembering across runs
CORRECTION = "correction"   # the human overrode the agent — the strongest learning signal
GOTCHA = "gotcha"           # a trap/pitfall worth remembering

INSIGHT = "insight"  # node/note type

# Interrogation rounds (dependency order).
ROUNDS = ("business", "technical", "qa")


@dataclass
class Question:
    """One clarifying question surfaced by refinement (a genuine judgement call)."""

    id: str
    round: str  # business | technical | qa
    question: str
    why: str = ""
    options: list[dict] = field(default_factory=list)  # [{"label", "implication"}]
    recommendation: str = ""
    depends_on: list[str] = field(default_factory=list)
    applies_to: str = ""
    status: str = "open"  # open | answered | self-answered | deferred
    confidence: str = "low"  # agent's confidence it can answer WITHOUT a human


@dataclass
class Answer:
    """A human (or agent-self) answer to one Question."""

    question_id: str
    answered_by: str = "human"  # human | agent-self
    chosen_option: str = ""
    text: str = ""
    answered_at: str = ""
    new_seed: str | None = None  # if set, re-seeds gathering (§ Gather↔Refine loop)


@dataclass
class Insight:
    """A distilled, provenance-carrying fact the refinement loop persists ('Collect insight')."""

    id: str  # e.g. "insight:run-6f2a:Q-biz-1"
    kind: str  # decision | assumption | clarification | gap-seed
    context_id: str
    question_id: str
    statement: str
    answered_by: str = "human"  # human | agent-self
    confidence: str = "high"  # high(=human) | medium | low(=agent-derived)
    source_refs: list[str] = field(default_factory=list)
    created_at: str = ""
    run_id: str = ""
    rationale: str = ""
    rejected: list[str] = field(default_factory=list)  # options considered and not chosen
    # --- self-learning provenance (L0); defaulted so old records stay readable --- #
    origin_step: str = ""       # gather | refine | define | implement | review
    scope: str = "context"      # context (this run only) | shared (promoted, cross-run)
    status: str = "active"      # active | vetoed | superseded
    supersedes: str = ""        # id of a lesson this one replaces


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
    gaps: list[str] = field(default_factory=list)  # open questions left at budget-end (declared)
    understanding_confidence: str = ""
    started: str = ""
    ended: str = ""


@dataclass
class IngestResult:
    """The outcome of matching a turn's raw answers back to their questions."""

    answers: list[Answer] = field(default_factory=list)
    answered: list[Question] = field(default_factory=list)  # questions that got an answer
    carried: list[Question] = field(default_factory=list)  # still open, unanswered this turn
    deferred: list[Question] = field(default_factory=list)  # explicitly set aside


@dataclass
class RefineResult:
    """The final result of a refine session — understanding, insights, gaps, re-seeds."""

    understanding: str = ""
    confidence: str = ""
    insights: list[Insight] = field(default_factory=list)
    open_gaps: list[str] = field(default_factory=list)  # question texts left open at budget-end
    new_seeds: list[str] = field(default_factory=list)
    run: RefinementRun | None = None
