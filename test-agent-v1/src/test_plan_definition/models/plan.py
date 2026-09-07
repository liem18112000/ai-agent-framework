"""Define-stage (Stage A) data contracts — the plan, its decisions, and the run result.

Stage A reuses `common.models`' generic `Question`/`Answer` and produces `PlanDecision`s that
assemble into a `TestPlan`; `TestPlanRun` is the run-log and `PlanResult` is what the define
loop returns. Plan lifecycle + define-round constants live here too.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Interrogation rounds for the define stage (dependency order) — the analog of
# common.models.ROUNDS = ("business", "technical", "qa").
ROUNDS = ("methodology", "scope", "metrics")

# Per-round question-id prefix (Q-mth-1, Q-sco-1, Q-mtr-1). Lives here (import-free) so both
# the heuristic generator and the LLM prompt share it without an import cycle.
ROUND_PREFIX = {"methodology": "mth", "scope": "sco", "metrics": "mtr"}

# TestPlan lifecycle.
DRAFT = "draft"
CONFIRMED = "confirmed"

# PlanDecision kinds (mirror the insight kinds: a human answer is a decision, an agent
# self-answer is a vetoable assumption).
DECISION = "decision"
ASSUMPTION = "assumption"

# Node/note type added to the shared knowledge graph + memory bank.
TEST_PLAN = "test-plan"


@dataclass
class TestPlan:
    """The confirmed plan the define stage restates and the human reconfirms."""

    id: str  # e.g. "plan:run-6f2a"
    context_id: str
    methodology: list[str] = field(default_factory=list)  # ["api"] for the POC; e2e/ui later
    scope: list[str] = field(default_factory=list)  # feature/service ids in scope
    out_of_scope: list[str] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)  # what "passed" means — the assertions
    confidence: str = "low"  # low | medium | high (same deterministic rule as refine)
    source_refs: list[str] = field(default_factory=list)  # insight/note ids this builds on
    status: str = DRAFT  # draft | confirmed
    created_at: str = ""
    run_id: str = ""


@dataclass
class PlanDecision:
    """A distilled, provenance-carrying decision from one answered define question."""

    id: str  # e.g. "plan-decision:run-6f2a:Q-mth-1"
    kind: str  # decision | assumption
    context_id: str
    question_id: str
    statement: str
    round: str = ""  # methodology | scope | metrics — which plan facet this settles
    chosen: str = ""  # the chosen option label/value (drives TestPlan assembly)
    answered_by: str = "human"  # human | agent-self
    confidence: str = "high"  # high(=human) | low(=agent self-answer)
    source_refs: list[str] = field(default_factory=list)
    created_at: str = ""
    run_id: str = ""
    rationale: str = ""
    rejected: list[str] = field(default_factory=list)  # options considered, not chosen


@dataclass
class TestPlanRun:
    """One run-log entry spanning a define and/or implement pass."""

    run_id: str
    context_id: str
    plan_id: str = ""
    rounds: list[str] = field(default_factory=list)
    questions_raised: int = 0
    questions_answered: int = 0
    decisions_written: int = 0
    scenarios_written: int = 0
    steps_written: int = 0
    testdata_written: int = 0
    gaps: list[str] = field(default_factory=list)  # open questions left at budget-end
    confidence: str = ""
    started: str = ""
    ended: str = ""


@dataclass
class PlanResult:
    """The final result of a define session — the plan, its brief, decisions, and gaps."""

    plan: TestPlan | None = None
    brief: str = ""
    decisions: list[PlanDecision] = field(default_factory=list)
    open_gaps: list[str] = field(default_factory=list)
    confidence: str = ""
    run: TestPlanRun | None = None
