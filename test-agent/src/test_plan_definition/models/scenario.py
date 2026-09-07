"""Implement-stage (Stage B) data contracts — test data, scenarios, steps, and the run result.

Stage B turns a confirmed `TestPlan` into `TestData`, `TestScenario`, and `TestStep` records;
`ImplementResult` is what the implement pass returns. Scenario/test-data kind constants and the
scenario graph-node type live here too.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from test_plan_definition.models.plan import TestPlan, TestPlanRun

# Node/note type added to the shared knowledge graph + memory bank.
TEST_SCENARIO = "test-scenario"

# TestScenario kinds (the coverage bar).
HAPPY = "happy"
NEGATIVE = "negative"
BOUNDARY = "boundary"
ERROR = "error"

# TestData kinds.
MOCK_DATA = "mock-data"
TEST_ACCOUNT = "test-account"
FIXTURE = "fixture"


@dataclass
class TestData:
    """A test-data need the scenarios depend on (mock data, a test account, a fixture)."""

    id: str
    kind: str  # mock-data | test-account | fixture
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
    kind: str = HAPPY  # happy | negative | boundary | error
    methodology: str = "api"  # api | e2e | ui
    description: str = ""  # what the case verifies, in one or two sentences
    rationale: str = ""  # why this case matters (what/how/why for case-by-case detail)
    preconditions: list[str] = field(default_factory=list)
    data_refs: list[str] = field(default_factory=list)  # TestData ids
    source_refs: list[str] = field(default_factory=list)  # insight/note ids
    created_at: str = ""


@dataclass
class TestStep:
    """One ordered step of a scenario (API: request -> assert)."""

    id: str
    scenario_id: str
    order: int
    action: str
    expected: str = ""
    keyword: str = ""  # BDD keyword: Given | When | Then | And (for step-by-step rendering)
    data_refs: list[str] = field(default_factory=list)


@dataclass
class ImplementResult:
    """The final result of an implement pass — plan, generated artifacts, and the Gherkin export."""

    plan: TestPlan | None = None
    test_data: list[TestData] = field(default_factory=list)
    scenarios: list[TestScenario] = field(default_factory=list)
    steps: list[TestStep] = field(default_factory=list)
    feature: str = ""  # the exported Gherkin .feature text
    run: TestPlanRun | None = None
    message: str = ""  # set when nothing was generated (no plan / not confirmed)
