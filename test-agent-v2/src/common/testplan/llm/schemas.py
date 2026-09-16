"""Pydantic output schemas for the implement LlmAgents (T0/§7).

ADK's ``LlmAgent(output_schema=...)`` requires a pydantic ``BaseModel`` — the rest of TPD models
are stdlib dataclasses, so these live here as the one validated LLM-parsing surface. Each generator
returns a JSON *array* of records; ADK wants an object, so we wrap the list as ``{"items": [...]}``
(``Scenarios``/``TestDataList``/``StepsList``). The per-field mapping + defaulting that the old
hand-parsers did (``loads_array`` + ``it.get(k)`` + ``setdefault``) now lives in the typed
``to_*`` adapters below, so it is one validated model instead of five tolerant hand-parsers.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


def _as_list(v):
    """Coerce a real model's list-field drift into a list — the fix for the deployed generator failing
    schema validation (``list_type``) → silent heuristic fallback. Claude-on-Vertex intermittently
    emits a bare scalar (``source_refs: "jira:X"``) or a single object where the schema wants a list;
    offline fakes always return clean lists, so this only bit in prod. None → [], scalar/dict → [it]."""
    if v is None:
        return []
    if isinstance(v, (str, bytes, dict)):
        return [v]
    return v  # already a list (or a genuinely wrong type → let pydantic reject it)


from common.testplan.models import HAPPY, TestData, TestPlan, TestScenario, TestStep


class InScope(BaseModel):
    """The scope classifier's output — the pack node ids that are IN scope for testing THIS ticket
    (the rest are sibling/framework/cross-project nodes the crawl swept in, kept only as context)."""

    in_scope_ids: list[str] = Field(default_factory=list)

    _coerce = field_validator("in_scope_ids", mode="before")(_as_list)


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

    _coerce = field_validator("preconditions", "data_refs", "source_refs", mode="before")(_as_list)


class Scenarios(BaseModel):
    """The scenario-generator output — replaces ``loads_array`` + the ``_FIELDS`` pick."""

    items: list[ScenarioItem] = Field(default_factory=list)

    _coerce = field_validator("items", mode="before")(_as_list)

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

    _coerce = field_validator("source_refs", mode="before")(_as_list)


class TestDataList(BaseModel):
    items: list[TestDataItem] = Field(default_factory=list)

    _coerce = field_validator("items", mode="before")(_as_list)

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


class JudgeVerdict(BaseModel):
    """LLM-as-judge output for the P4 assured loop (§3.4). Each dimension is 0.0–1.0; ``reflections``
    are imperative fixes fed back into the next generation (reflexion). ``accept`` is advisory — the
    loop gates on ``overall`` vs its threshold, not on the model's own accept flag."""

    overall: float = 0.0
    ac_coverage: float = 0.0
    atomicity: float = 0.0
    testability: float = 0.0
    traceability: float = 0.0
    faithfulness: float = 0.0
    negative_edge_coverage: float = 0.0
    non_duplication: float = 0.0
    accept: bool = False
    issues: list[str] = Field(default_factory=list)
    reflections: list[str] = Field(default_factory=list)

    _coerce = field_validator("issues", "reflections", mode="before")(_as_list)

    _DIMS = ("ac_coverage", "atomicity", "testability", "traceability", "faithfulness",
             "negative_edge_coverage", "non_duplication")

    def score(self) -> float:
        """The overall 0–1 quality score: the model's ``overall`` when it gave one, else the mean of
        the seven rubric dimensions (so a judge that scored dimensions but forgot the summary still
        yields a usable number). Clamped to [0, 1]."""
        raw = self.overall if self.overall > 0 else (
            sum(getattr(self, d) for d in self._DIMS) / len(self._DIMS))
        return max(0.0, min(1.0, raw))


class StepItem(BaseModel):
    scenario_id: str = ""
    steps: list[dict] = Field(default_factory=list)  # {order, keyword, action, expected}

    _coerce = field_validator("steps", mode="before")(_as_list)


class StepsList(BaseModel):
    items: list[StepItem] = Field(default_factory=list)

    _coerce = field_validator("items", mode="before")(_as_list)

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
