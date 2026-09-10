"""Implement-stage (Stage B) data contracts — test data, scenarios, steps, and the run result."""

from __future__ import annotations

from dataclasses import dataclass, field

from common.testplan.models.plan import TestPlan, TestPlanRun

TEST_SCENARIO = "test-scenario"

HAPPY = "happy"
NEGATIVE = "negative"
BOUNDARY = "boundary"
ERROR = "error"

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
