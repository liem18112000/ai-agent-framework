"""Implement-stage (Stage B) data contracts — test data, scenarios, steps, and the run result."""

from __future__ import annotations

from dataclasses import dataclass, field

from common.testplan.models.plan import TestPlan, TestPlanRun

TEST_SCENARIO = "test-scenario"

HAPPY = "happy"
NEGATIVE = "negative"
BOUNDARY = "boundary"
ERROR = "error"

DEFAULT_KINDS = (HAPPY, NEGATIVE, BOUNDARY, ERROR)


def effective_kinds(plan: TestPlan) -> list[str]:
    """The kinds a plan must cover: the base four ∪ any elicited extras (``test_kinds``). ADDITIVE —
    the four defaults are a seed the open taxonomy EXTENDS, never replaces. The old ``test_kinds or
    defaults`` REPLACED them, so a single mangled kind (e.g. the implement fold-in collapsing
    ``test_kinds`` to ``["performance"]`` when it was empty) silently dropped happy/negative/boundary/
    error and produced a defaults-less garbage suite. ``metrics`` declaring happy-only is the one
    intentional collapse. Single source of truth for the heuristic generator, the LLM prompt, the
    coverage matrix, and the HTML report."""
    metrics = " ".join(plan.metrics or []).lower()
    if "happy only" in metrics or "happy-only" in metrics:
        return [HAPPY]
    return list(dict.fromkeys([*DEFAULT_KINDS, *(plan.test_kinds or [])]))


MOCK_DATA = "mock-data"
TEST_ACCOUNT = "test-account"
FIXTURE = "fixture"


@dataclass
class TestData:
    """A test-data need the scenarios depend on (mock data, a test account, a fixture)."""

    id: str
    kind: str
    plan_id: str = ""
    spec: dict = field(default_factory=dict)
    source_refs: list[str] = field(default_factory=list)
    created_at: str = ""


@dataclass
class TestScenario:
    """One case to verify — traced back to the insight/AC it covers."""

    id: str
    plan_id: str
    title: str
    kind: str = HAPPY
    methodology: str = "api"
    description: str = ""
    rationale: str = ""
    preconditions: list[str] = field(default_factory=list)
    data_refs: list[str] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)
    created_at: str = ""


@dataclass
class TestStep:
    """One ordered step of a scenario (API: request -> assert)."""

    id: str
    scenario_id: str
    order: int
    action: str
    expected: str = ""
    keyword: str = ""
    data_refs: list[str] = field(default_factory=list)


@dataclass
class AssuredReport:
    """The P4 assured-loop verdict (§3.4): the quality signal attached to an implement pass. One
    ``iterations`` entry per generate→judge round; ``accepted`` once ``final_score >= threshold``.
    Persisted under the context so the loop resumes rather than restarts across a Cloud Run kill."""

    iterations: list[dict] = field(default_factory=list)  # {iter, score, accepted, issues}
    final_score: float = 0.0
    threshold: float = 0.0
    accepted: bool = False
    issues: list[str] = field(default_factory=list)
    reflections: list[str] = field(default_factory=list)
    note: str = ""

    @property
    def rounds(self) -> int:
        return len(self.iterations)


@dataclass
class ImplementResult:
    """The final result of an implement pass — plan, generated artifacts, and the Gherkin export."""

    plan: TestPlan | None = None
    test_data: list[TestData] = field(default_factory=list)
    scenarios: list[TestScenario] = field(default_factory=list)
    steps: list[TestStep] = field(default_factory=list)
    feature: str = ""
    run: TestPlanRun | None = None
    message: str = ""
    quality: AssuredReport | None = None
    coverage_summary: str = ""  # Q5 one-line coverage-matrix summary (full matrix persisted)
    done: bool = True  # False = the assured loop paused mid-way (more rounds pending); re-run to continue
