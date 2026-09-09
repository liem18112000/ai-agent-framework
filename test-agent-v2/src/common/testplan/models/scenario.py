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
class ImplementResult:
    """The final result of an implement pass — plan, generated artifacts, and the Gherkin export."""

    plan: TestPlan | None = None
    test_data: list[TestData] = field(default_factory=list)
    scenarios: list[TestScenario] = field(default_factory=list)
    steps: list[TestStep] = field(default_factory=list)
    feature: str = ""
    run: TestPlanRun | None = None
    message: str = ""
