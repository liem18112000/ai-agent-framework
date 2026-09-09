"""Pydantic output schemas for the implement LlmAgents (T0/§7).

ADK's ``LlmAgent(output_schema=...)`` requires a pydantic ``BaseModel`` — the rest of TPD models
are stdlib dataclasses, so these live here as the one validated LLM-parsing surface. Each generator
returns a JSON *array* of records; ADK wants an object, so we wrap the list as ``{"items": [...]}``
(``Scenarios``/``TestDataList``/``StepsList``). The per-field mapping + defaulting that the old
hand-parsers did (``loads_array`` + ``it.get(k)`` + ``setdefault``) now lives in the typed
``to_*`` adapters below, so it is one validated model instead of five tolerant hand-parsers.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from test_plan_definition.models import HAPPY, TestData, TestPlan, TestScenario, TestStep


class ScenarioItem(BaseModel):
    id: str = ""
    title: str = ""
    kind: str = ""
    methodology: str = ""
    description: str = ""
    rationale: str = ""
    preconditions: list[str] = Field(default_factory=list)
    data_refs: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)


class Scenarios(BaseModel):
    """The scenario-generator output — replaces ``loads_array`` + the ``_FIELDS`` pick."""

    items: list[ScenarioItem] = Field(default_factory=list)

    def to_scenarios(self, plan: TestPlan, now: str = "") -> list[TestScenario]:
        default_method = plan.methodology[0] if plan.methodology else "api"
        return [
            TestScenario(
                id=it.id,
                plan_id=plan.id,
                title=it.title,
                kind=it.kind or HAPPY,
                methodology=it.methodology or default_method,
                description=it.description,
                rationale=it.rationale,
                preconditions=it.preconditions,
                data_refs=it.data_refs,
                source_refs=it.source_refs,
                created_at=now,
            )
            for it in self.items
        ]


class TestDataItem(BaseModel):
    id: str = ""
    kind: str = ""
    spec: dict = Field(default_factory=dict)
    source_refs: list[str] = Field(default_factory=list)


class TestDataList(BaseModel):
    items: list[TestDataItem] = Field(default_factory=list)

    def to_test_data(self, plan: TestPlan, now: str = "") -> list[TestData]:
        return [
            TestData(
                id=it.id,
                kind=it.kind,
                plan_id=plan.id,
                spec=it.spec,
                source_refs=it.source_refs,
                created_at=now,
            )
            for it in self.items
            if it.id and it.kind
        ]


class StepItem(BaseModel):
    scenario_id: str = ""
    steps: list[dict] = Field(default_factory=list)  # {order, keyword, action, expected}


class StepsList(BaseModel):
    items: list[StepItem] = Field(default_factory=list)

    def to_steps(self, test_data: list[TestData]) -> dict[str, list[TestStep]]:
        data_refs = [d.id for d in test_data]
        by_id: dict[str, list[TestStep]] = {}
        for it in self.items:
            if not it.scenario_id:
                continue
            steps = [TestStep(id=f"{it.scenario_id}#s{(order := s.get('order', i))}",
                              scenario_id=it.scenario_id, order=order, action=s.get("action", ""),
                              expected=s.get("expected", ""), keyword=s.get("keyword", ""),
                              data_refs=data_refs)
                     for i, s in enumerate(it.steps or [], start=1)]
            if steps:
                by_id[it.scenario_id] = steps
        return by_id
