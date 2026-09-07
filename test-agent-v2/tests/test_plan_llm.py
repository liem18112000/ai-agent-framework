"""M6 tests: the Claude-on-Vertex seams — selection by VERTEX_* + JSON parsing.

No real Vertex call: `complete` is monkeypatched in each llm module to return canned JSON, so
the whole Claude path (prompt build is exercised, parse, dataclass build) runs offline and
deterministically. When VERTEX_* is unset the heuristic path is selected.
"""

from __future__ import annotations

import json

import pytest

from common.interrogate.pack import Pack
from common.llm.parse import loads_array
from test_plan_definition.define.plan import make_restater
from test_plan_definition.define.questions import heuristic_questions, make_generator
from test_plan_definition.implement.scenarios import generate_scenarios, heuristic_scenarios
from test_plan_definition.implement.steps import _pass_metric
from test_plan_definition.models import TestData, TestPlan
from test_plan_definition.pack import PlanPack


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


# --- parse helper --- #

def test_loads_array_strips_fence_and_rejects_non_arrays():
    assert loads_array('```json\n[{"a":1}]\n```') == [{"a": 1}]
    assert loads_array("not json") is None
    assert loads_array('{"a": 1}') is None  # object, not array


# --- selection: heuristic when VERTEX_* unset --- #

def test_make_generator_defaults_to_heuristic(monkeypatch):
    monkeypatch.delenv("VERTEX_PROJECT", raising=False)
    gen = make_generator("understanding")
    qs = gen(_plan_pack().pack, "methodology")
    # identical to calling the heuristic directly (no LLM involved)
    assert qs and qs[0].round == "methodology"
    assert [q.id for q in qs] == [q.id for q in heuristic_questions(_plan_pack().pack, "u", "methodology")]


def test_make_restater_defaults_to_heuristic(monkeypatch):
    monkeypatch.delenv("VERTEX_PROJECT", raising=False)
    assert make_restater().__name__ == "heuristic_brief"


# --- Claude path (complete monkeypatched) --- #

def test_make_generator_uses_claude_when_configured(vertex_env, monkeypatch):
    canned = json.dumps([{"id": "Q-mth-1", "question": "Which methodology?",
                          "options": [{"label": "API", "implication": "x"}],
                          "recommendation": "API", "status": "open"}])
    monkeypatch.setattr("test_plan_definition.llm.questions.complete", lambda *a, **k: canned)
    gen = make_generator("understanding")
    qs = gen(_plan_pack().pack, "methodology")
    assert len(qs) == 1 and qs[0].id == "Q-mth-1" and qs[0].round == "methodology"


def test_claude_question_coerces_list_applies_to(vertex_env, monkeypatch):
    # The LLM sometimes returns applies_to as a list; left as-is it becomes an unhashable
    # source_ref that crashes assemble_plan (the define_plan run-990d0017 regression).
    canned = json.dumps([{"id": "Q-sco-1", "question": "Scope?", "applies_to": ["LUZ-1", "LUZ-2"],
                          "options": [{"label": "In", "implication": "x"}],
                          "recommendation": "In", "status": "open"}])
    monkeypatch.setattr("test_plan_definition.llm.questions.complete", lambda *a, **k: canned)
    qs = make_generator("u")(_plan_pack().pack, "scope")
    assert isinstance(qs[0].applies_to, str) and qs[0].applies_to == "LUZ-1, LUZ-2"


def test_make_generator_falls_back_to_heuristic_when_claude_empty(vertex_env, monkeypatch):
    # unparseable LLM output -> claude_plan_questions returns [] -> heuristic fills the round,
    # so a define round is never silently blank (define-side mirror of the refine fallback).
    monkeypatch.setattr("test_plan_definition.llm.questions.complete", lambda *a, **k: "oops")
    qs = make_generator("understanding")(_plan_pack().pack, "methodology")
    assert qs and qs[0].round == "methodology"  # not empty — fallback fired
    assert [q.id for q in qs] == [
        q.id for q in heuristic_questions(_plan_pack().pack, "understanding", "methodology")]


def test_claude_brief_path(vertex_env, monkeypatch):
    monkeypatch.setattr("test_plan_definition.llm.plan.complete", lambda *a, **k: "## Brief\nok")
    brief = make_restater()(_plan(), _plan_pack(), [])
    assert "Brief" in brief


def test_generate_scenarios_uses_claude_then_falls_back(vertex_env, monkeypatch):
    canned = json.dumps([{"id": "scenario:run-x:a", "title": "A", "kind": "happy",
                          "source_refs": ["jira:LUZ-1"]}])
    monkeypatch.setattr("test_plan_definition.llm.scenarios.complete", lambda *a, **k: canned)
    scs = generate_scenarios(_plan(), _plan_pack(), [TestData(id="td", kind="mock-data")])
    assert len(scs) == 1 and scs[0].id == "scenario:run-x:a" and scs[0].plan_id == "plan:run-x"

    # garbage output -> None -> heuristic fallback (still returns scenarios)
    monkeypatch.setattr("test_plan_definition.llm.scenarios.complete", lambda *a, **k: "oops")
    scs2 = generate_scenarios(_plan(), _plan_pack(), [TestData(id="td", kind="mock-data")])
    assert scs2 == heuristic_scenarios(_plan(), _plan_pack(), [TestData(id="td", kind="mock-data")])


# --- pass-metric polish --- #

def test_pass_metric_prefers_the_non_coverage_metric():
    assert _pass_metric(_plan()) == "End-state verified"
