"""M6 tests: the Claude-on-Vertex seams — selection by VERTEX_* + JSON parsing."""

from __future__ import annotations

import json

import pytest

from common.interrogate.pack import Pack
from common.llm.parse import loads_array
from common.testplan.models import TestData, TestPlan
from common.testplan.pack import PlanPack
from test_plan_definition.define.plan import make_restater
from test_plan_definition.define.questions import heuristic_questions, make_generator
from test_plan_definition.implement.scenarios import generate_scenarios, heuristic_scenarios
from test_plan_definition.implement.steps import _pass_metric


@pytest.fixture
def vertex_env(monkeypatch):
    monkeypatch.setenv("VERTEX_PROJECT", "p")
    monkeypatch.setenv("VERTEX_LOCATION", "us-east5")
    monkeypatch.setenv("VERTEX_MODEL", "claude-sonnet-5")


def _plan_pack() -> PlanPack:
    return PlanPack(pack=Pack(context_id="run-x", seed="LUZ-1"), understanding="X is done.")


def _plan() -> TestPlan:
    return TestPlan(id="plan:run-x", context_id="run-x", methodology=["api"],
                    scope=["jira:LUZ-1"], metrics=["End-state verified", "+ negative for risk"])


def test_loads_array_strips_fence_and_rejects_non_arrays():
    assert loads_array('```json\n[{"a":1}]\n```') == [{"a": 1}]
    assert loads_array("not json") is None
    assert loads_array('{"a": 1}') is None


def test_make_generator_defaults_to_heuristic(monkeypatch):
    monkeypatch.delenv("VERTEX_PROJECT", raising=False)
    gen = make_generator("understanding")
    qs = gen(_plan_pack().pack, "methodology")
    assert qs and qs[0].round == "methodology"
    assert [q.id for q in qs] == [q.id for q in heuristic_questions(_plan_pack().pack, "methodology")]


def test_make_restater_defaults_to_heuristic(monkeypatch):
    monkeypatch.delenv("VERTEX_PROJECT", raising=False)
    assert make_restater().__name__ == "heuristic_brief"


def test_make_generator_uses_claude_when_configured(vertex_env, monkeypatch):
    canned = json.dumps([{"id": "Q-mth-1", "question": "Which methodology?",
                          "options": [{"label": "API", "implication": "x"}],
                          "recommendation": "API", "status": "open"}])
    monkeypatch.setattr("test_plan_definition.define.llm.complete", lambda *a, **k: canned)
    gen = make_generator("understanding")
    qs = gen(_plan_pack().pack, "methodology")
    assert len(qs) == 1 and qs[0].id == "Q-mth-1" and qs[0].round == "methodology"


def test_claude_question_coerces_list_applies_to(vertex_env, monkeypatch):
    canned = json.dumps([{"id": "Q-sco-1", "question": "Scope?", "applies_to": ["LUZ-1", "LUZ-2"],
                          "options": [{"label": "In", "implication": "x"}],
                          "recommendation": "In", "status": "open"}])
    monkeypatch.setattr("test_plan_definition.define.llm.complete", lambda *a, **k: canned)
    qs = make_generator("u")(_plan_pack().pack, "scope")
    assert isinstance(qs[0].applies_to, str) and qs[0].applies_to == "LUZ-1, LUZ-2"


def test_make_generator_falls_back_to_heuristic_when_claude_empty(vertex_env, monkeypatch):
    monkeypatch.setattr("test_plan_definition.define.llm.complete", lambda *a, **k: "oops")
    qs = make_generator("understanding")(_plan_pack().pack, "methodology")
    assert qs and qs[0].round == "methodology"
    assert [q.id for q in qs] == [
        q.id for q in heuristic_questions(_plan_pack().pack, "methodology")]


def test_claude_brief_path(vertex_env, monkeypatch):
    monkeypatch.setattr("test_plan_definition.define.llm.complete", lambda *a, **k: "## Brief\nok")
    brief = make_restater()(_plan(), _plan_pack(), [])
    assert "Brief" in brief


async def test_generate_scenarios_uses_llm_agent_then_falls_back():
    """ScenarioGen is an ADK LlmAgent driven by an injected fake model; invalid output → heuristic."""
    from tests.tpd_fakes import FakeGeneratorModel, scenarios_json

    fake = FakeGeneratorModel(model="fake", scenarios_json=scenarios_json(
        [{"id": "scenario:run-x:a", "title": "A", "kind": "happy", "source_refs": ["jira:LUZ-1"]}]))
    scs = await generate_scenarios(
        _plan(), _plan_pack(), [TestData(id="td", kind="mock-data")], model=fake)
    assert len(scs) == 1 and scs[0].id == "scenario:run-x:a" and scs[0].plan_id == "plan:run-x"
    assert fake.calls == 1

    bad = FakeGeneratorModel(model="fake", scenarios_json="oops not json")
    scs2 = await generate_scenarios(
        _plan(), _plan_pack(), [TestData(id="td", kind="mock-data")], model=bad)
    assert scs2 == heuristic_scenarios(_plan(), _plan_pack(), [TestData(id="td", kind="mock-data")])


def test_pass_metric_prefers_the_non_coverage_metric():
    assert _pass_metric(_plan()) == "End-state verified"
