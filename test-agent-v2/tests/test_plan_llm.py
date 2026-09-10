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
from test_plan_definition.implement.generate.scenarios import (
    generate_scenarios,
    heuristic_scenarios,
)
from test_plan_definition.implement.generate.steps import _pass_metric


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
    monkeypatch.setattr("test_plan_definition.define.questions.complete", lambda *a, **k: canned)
    gen = make_generator("understanding")
    qs = gen(_plan_pack().pack, "methodology")
    assert len(qs) == 1 and qs[0].id == "Q-mth-1" and qs[0].round == "methodology"


def test_claude_question_coerces_list_applies_to(vertex_env, monkeypatch):
    canned = json.dumps([{"id": "Q-sco-1", "question": "Scope?", "applies_to": ["LUZ-1", "LUZ-2"],
                          "options": [{"label": "In", "implication": "x"}],
                          "recommendation": "In", "status": "open"}])
    monkeypatch.setattr("test_plan_definition.define.questions.complete", lambda *a, **k: canned)
    qs = make_generator("u")(_plan_pack().pack, "scope")
    assert isinstance(qs[0].applies_to, str) and qs[0].applies_to == "LUZ-1, LUZ-2"


def test_make_generator_falls_back_to_heuristic_when_claude_empty(vertex_env, monkeypatch):
    monkeypatch.setattr("test_plan_definition.define.questions.complete", lambda *a, **k: "oops")
    qs = make_generator("understanding")(_plan_pack().pack, "methodology")
    assert qs and qs[0].round == "methodology"
    assert [q.id for q in qs] == [
        q.id for q in heuristic_questions(_plan_pack().pack, "methodology")]


def test_claude_brief_path(vertex_env, monkeypatch):
    monkeypatch.setattr("test_plan_definition.define.plan.complete", lambda *a, **k: "## Brief\nok")
    brief = make_restater()(_plan(), _plan_pack(), [])
    assert "Brief" in brief


def test_generator_caches_the_pack_prefix(vertex_env, monkeypatch):
    """The pack (stable across rounds) is passed as complete(cache_prefix=…), NOT baked into the user
    prompt — so Anthropic prompt-caches it and rounds 2-4 hit the cache."""
    captured: dict = {}

    def fake_complete(prompt, **kw):
        captured.update(prompt=prompt, cache_prefix=kw.get("cache_prefix"))
        return json.dumps([{"id": "Q-mth-1", "question": "Q?", "status": "open",
                            "options": [{"label": "A", "implication": "x"}], "recommendation": "A"}])

    monkeypatch.setattr("test_plan_definition.define.questions.complete", fake_complete)
    make_generator("understanding")(_plan_pack().pack, "methodology")
    assert captured["cache_prefix"] and captured["cache_prefix"].startswith("Context pack:")
    assert "Context pack:" not in captured["prompt"]  # moved out of the variable user prompt


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


async def test_adk_generator_caches_pack_in_system_task_in_user():
    """ADK-path caching split: the stable pack is the agent's system instruction (cache-injected on
    the LiteLlm path); the per-call TASK is the user message. The pack is NOT duplicated in the task."""
    from test_plan_definition.implement.generate.llm import claude_scenarios
    from tests.tpd_fakes import FakeGeneratorModel, scenarios_json

    seen: dict = {}

    class Recorder(FakeGeneratorModel):
        async def generate_content_async(self, llm_request, stream: bool = False):
            si = getattr(getattr(llm_request, "config", None), "system_instruction", None)
            seen["system"] = si if isinstance(si, str) else "".join(
                p.text for p in (getattr(si, "parts", None) or []) if getattr(p, "text", None))
            seen["user"] = " ".join(
                p.text for c in (llm_request.contents or []) for p in (getattr(c, "parts", None) or [])
                if getattr(p, "text", None))
            async for r in super().generate_content_async(llm_request, stream):
                yield r

    fake = Recorder(model="fake", scenarios_json=scenarios_json(
        [{"id": "scenario:run-x:a", "title": "A", "kind": "happy", "source_refs": ["jira:LUZ-1"]}]))
    await claude_scenarios(_plan(), _plan_pack(), [TestData(id="td", kind="mock-data")], model=fake)

    assert seen["system"].startswith("Context pack:")   # the cacheable shared prefix
    assert "TEST SCENARIOS" in seen["user"]              # the per-call task went to the user turn
    assert "Context pack:" not in seen["user"]           # pack not duplicated into the task
