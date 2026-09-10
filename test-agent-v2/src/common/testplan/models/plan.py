"""Define-stage (Stage A) data contracts — the plan, its decisions, and the run result."""

from __future__ import annotations

from dataclasses import dataclass, field

ROUNDS = ("methodology", "scope", "metrics", "test-design")

ROUND_PREFIX = {"methodology": "mth", "scope": "sco", "metrics": "mtr", "test-design": "tds"}

DRAFT = "draft"
CONFIRMED = "confirmed"

DECISION = "decision"
ASSUMPTION = "assumption"

TEST_PLAN = "test-plan"


@dataclass
class TestPlan:
    """The confirmed plan the define stage restates and the human reconfirms."""

    id: str
    context_id: str
    methodology: list[str] = field(default_factory=list)
    scope: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)
    test_design: list[str] = field(default_factory=list)  # chosen test-design method(s), 4th round
    test_kinds: list[str] = field(default_factory=list)  # open, elicited kind taxonomy (empty = defaults)
    confidence: str = "low"
    source_refs: list[str] = field(default_factory=list)
    status: str = DRAFT
    created_at: str = ""
    run_id: str = ""


@dataclass
class PlanDecision:
    """A distilled, provenance-carrying decision from one answered define question."""

    id: str
    kind: str
    context_id: str
    question_id: str
    statement: str
    round: str = ""
    chosen: str = ""
    answered_by: str = "human"
    confidence: str = "high"
    source_refs: list[str] = field(default_factory=list)
    created_at: str = ""
    run_id: str = ""
    rationale: str = ""
    rejected: list[str] = field(default_factory=list)


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
    gaps: list[str] = field(default_factory=list)
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
