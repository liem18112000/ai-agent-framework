"""Data contracts for the Test-Plan Definition agent (stdlib dataclasses).

Split into cohesive submodules — `plan` (Stage A: the plan, its decisions, define constants),
`scenario` (Stage B: test data / scenarios / steps, coverage constants), and `pack` (the
`PlanPack` input) — and re-exported flat here so callers keep using
`from test_plan_definition.models import <name>` unchanged. Generic contracts (`Question`,
`Answer`, `Graph`, ...) stay in `common.models`.
"""

from test_plan_definition.models.pack import PlanPack
from test_plan_definition.models.plan import (
    ASSUMPTION,
    CONFIRMED,
    DECISION,
    DRAFT,
    ROUND_PREFIX,
    ROUNDS,
    TEST_PLAN,
    PlanDecision,
    PlanResult,
    TestPlan,
    TestPlanRun,
)
from test_plan_definition.models.scenario import (
    BOUNDARY,
    ERROR,
    FIXTURE,
    HAPPY,
    MOCK_DATA,
    NEGATIVE,
    TEST_ACCOUNT,
    TEST_SCENARIO,
    ImplementResult,
    TestData,
    TestScenario,
    TestStep,
)

__all__ = [
    "ASSUMPTION",
    "BOUNDARY",
    "CONFIRMED",
    "DECISION",
    "DRAFT",
    "ERROR",
    "FIXTURE",
    "HAPPY",
    "MOCK_DATA",
    "NEGATIVE",
    "ROUNDS",
    "ROUND_PREFIX",
    "TEST_ACCOUNT",
    "TEST_PLAN",
    "TEST_SCENARIO",
    "ImplementResult",
    "PlanDecision",
    "PlanPack",
    "PlanResult",
    "TestData",
    "TestPlan",
    "TestPlanRun",
    "TestScenario",
    "TestStep",
]
