"""M6 tests: the Claude-on-Vertex seams — selection by VERTEX_* + JSON parsing."""

from __future__ import annotations

import json

import pytest

from common.interrogate.pack import Pack
from common.llm.parse import loads_array
from common.testplan.models import TestData, TestPlan, TestScenario
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


def _multi_pack(n: int) -> PlanPack:
    """A pack with ``n`` grounded notes — enough to force the generator to batch (>_BATCH_UNITS)."""
    from common.models.graph import Note
    notes = [Note(id=f"jira:U{i}", type="jira", title=f"Unit {i}", synopsis=f"unit {i} does a thing")
             for i in range(n)]
    return PlanPack(pack=Pack(context_id="run-x", seed="LUZ-1", notes=notes), understanding="X.")


async def test_claude_scenarios_batches_units_and_dedups():
    """13 grounded units → ceil(13/6)=3 generation calls (one per batch); merged output dedups by id."""
    from test_plan_definition.implement.generate.llm import _BATCH_UNITS, claude_scenarios
    from tests.tpd_fakes import FakeGeneratorModel, scenarios_json

    assert _BATCH_UNITS == 6
    pack = _multi_pack(13)
    # every batch returns the SAME two ids → 3 calls, but the merge collapses to 2 unique scenarios.
    fake = FakeGeneratorModel(model="fake", scenarios_json=scenarios_json(
        [{"id": "scenario:run-x:a", "title": "A", "kind": "happy", "source_refs": ["jira:U0"]},
         {"id": "scenario:run-x:b", "title": "B", "kind": "negative", "source_refs": ["jira:U1"]}]))
    scs = await claude_scenarios(_plan(), pack, [TestData(id="td", kind="mock-data")], model=fake)
    assert fake.calls == 3                                  # 6 + 6 + 1 units → 3 batched calls
    assert [s.id for s in scs] == ["scenario:run-x:a", "scenario:run-x:b"]   # deduped across batches


async def test_claude_scenarios_total_degrade_returns_none_and_wrapper_uses_full_heuristic():
    """When EVERY batch's output is invalid, claude_scenarios returns None (so the assured loop flags
    'degraded'); generate_scenarios then falls back to the whole-suite heuristic — nothing lost."""
    from test_plan_definition.implement.generate.llm import claude_scenarios
    from tests.tpd_fakes import FakeGeneratorModel

    pack = _multi_pack(13)
    td = [TestData(id="td", kind="mock-data")]
    bad = FakeGeneratorModel(model="fake", scenarios_json="not json")   # every batch fails schema
    assert await claude_scenarios(_plan(), pack, td, model=bad) is None
    assert bad.calls == 3                                              # all 3 batches were attempted
    bad2 = FakeGeneratorModel(model="fake", scenarios_json="not json")
    scs = await generate_scenarios(_plan(), pack, td, model=bad2)
    assert scs == heuristic_scenarios(_plan(), pack, td)              # wrapper degrades to full heuristic


def test_refine_scenarios_drops_untraceable_and_near_duplicates():
    """P2 cleanup: keep only scenarios citing a real pack id (lenient match), and collapse near-dupes
    (same kind + folded title); order preserved."""
    from test_plan_definition.implement.generate.scenarios import refine_scenarios

    scs = [
        TestScenario(id="s1", plan_id="p", title="Upload a valid zip", kind="happy",
                     source_refs=["jira:LUZ-158230"]),                     # traceable (exact)
        TestScenario(id="s2", plan_id="p", title="Upload  a  VALID zip!", kind="happy",
                     source_refs=["LUZ-158230"]),                          # near-dup of s1 (lenient id ok)
        TestScenario(id="s3", plan_id="p", title="Reject >2GB zip", kind="boundary",
                     source_refs=["invented:node"]),                       # untraceable → dropped
        TestScenario(id="s4", plan_id="p", title="Reject >2GB zip", kind="boundary",
                     source_refs=["codegraph:luz_docs_import"]),           # traceable, distinct kind/title
    ]
    valid = {"jira:LUZ-158230", "codegraph:luz_docs_import"}
    out = refine_scenarios(scs, valid)
    assert [s.id for s in out] == ["s1", "s4"]   # s2 deduped, s3 dropped as untraceable


def test_scenarios_prompt_injects_scope_boundary():
    """The generator prompt now names the confirmed In/Out scope so the model doesn't cover siblings."""
    from common.testplan.llm.prompts import scenarios_prompt

    plan = _plan()
    plan.scope = ["docs-import zip upload"]
    plan.out_of_scope = ["Agentic-Framework self-check"]
    body = scenarios_prompt(plan, "pack", [], include_context=False)
    assert "In scope (cover ONLY these behaviours): docs-import zip upload" in body
    assert "Agentic-Framework self-check" in body  # out-of-scope items named for the model to exclude


def test_judge_prompt_is_scope_aware():
    """The judge (the assured-loop gate) must see the scope boundary + elicited kinds, else it grades
    an out-of-scope scenario the same as in-scope and its reflections steer regeneration wrong."""
    from common.testplan.llm.prompts import judge_scenarios_prompt

    plan = _plan()
    plan.scope = ["docs-import upload"]
    plan.out_of_scope = ["Agentic-Framework sibling"]
    plan.test_kinds = ["security"]
    body = judge_scenarios_prompt(plan, "pack", [], include_context=False)
    assert "In scope (cover ONLY these behaviours): docs-import upload" in body
    assert "Agentic-Framework sibling" in body            # judge told what to penalise as out-of-scope
    assert "security" in body                              # elicited extra kind reaches the judge


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
