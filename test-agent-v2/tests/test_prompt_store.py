"""Prompt store (P0-P4): port, rendering, rails, ADK adapter, pinning."""

from __future__ import annotations

import pytest

from common.prompts import (
    NONE,
    PromptNotFound,
    PromptTemplate,
    PyPromptStore,
    declared_vars,
    reset_store_cache,
    store_for,
    validate,
)
from common.testplan.llm import templates


# --- port -----------------------------------------------------------------------------------------
def test_render_substitutes_params_and_preserves_literal_braces():
    """The whole reason the engine is $-substitution: our bodies are full of literal JSON braces that
    must reach the model untouched. `str.format` would raise (or eat) every one of them."""
    tpl = PromptTemplate(key="k", body='Cover $kinds.\nReturn {"items": [ ... ]} with {id, title}.',
                         required_vars=("kinds",))
    out = tpl.render({"kinds": "happy, negative"})
    assert "Cover happy, negative." in out
    assert '{"items": [ ... ]}' in out and "{id, title}" in out


def test_render_rejects_a_missing_param():
    """A half-rendered prompt ships '$scope_block' to the model as if it were an instruction — worse
    than crashing, so missing params are a hard error."""
    tpl = PromptTemplate(key="k", body="In scope: $scope_block", required_vars=("scope_block",))
    with pytest.raises(ValueError, match="missing params"):
        tpl.render({})
    assert tpl.render({"scope_block": "x", "unused": "y"})  # a superset is fine


def test_declared_vars_finds_both_placeholder_spellings():
    assert declared_vars("$a and ${b} and $a again") == ("a", "b")


def test_py_store_get_and_missing_key():
    store = PyPromptStore({"k": PromptTemplate(key="k", body="b")})
    assert store.get("k").body == "b"
    with pytest.raises(PromptNotFound):
        store.get("nope")


# --- rails (§4.5) ---------------------------------------------------------------------------------
def test_validate_rejects_undeclared_placeholder_and_bad_engine():
    """An undeclared $foo renders as the literal text '$foo' inside the prompt."""
    with pytest.raises(ValueError, match="undeclared placeholders"):
        validate("k", "hello $foo", NONE, ())
    with pytest.raises(ValueError, match="unknown engine"):
        validate("k", "hello", "wat", ())
    with pytest.raises(ValueError, match="empty body"):
        validate("k", "   ", NONE, ())
    validate("k", "hello $foo", NONE, ("foo",))  # declared -> fine


def test_every_shipped_template_passes_validation():
    for key, tpl in templates.DEFAULTS.items():
        validate(key, tpl.body, tpl.engine, tpl.required_vars)


def test_generator_templates_declare_the_object_schema_contract():
    """THE regression rail. Three rebuilds this week were spent on prompts that asked for a bare JSON
    array while the ADK output_schema is an object wrapper — recovery then parsed a single element and
    the batch silently degraded to the heuristic. Now that bodies are editable data, a published typo
    could reintroduce it, so pin each generator's declared output shape."""
    for key, contract in templates.SCHEMA_CONTRACT.items():
        body = templates.DEFAULTS[key].body
        assert contract in body, f"{key} no longer declares {contract!r}"
        assert "Return ONLY a JSON array" not in body, f"{key} asks for a bare array"


# --- ADK adapter ----------------------------------------------------------------------------------
async def test_instruction_from_returns_an_awaitable_provider():
    """ADK's canonical_instruction awaits the provider's result, so a store-backed (potentially
    I/O-bound) provider is legal. Rendering happens in the provider because passing a callable sets
    bypass_state_injection=True — ADK will NOT template the result for us."""
    from common.prompts.adk import instruction_from, static_provider

    store = PyPromptStore({"k": PromptTemplate(key="k", body="Kinds: $kinds", required_vars=("kinds",))})
    provider = instruction_from(store, "k", params={"kinds": "happy"})
    assert await provider(None) == "Kinds: happy"
    assert static_provider("verbatim {braces}")(None) == "verbatim {braces}"


# --- factory + pinning (P4) -----------------------------------------------------------------------
def test_store_for_falls_back_to_python_defaults_without_a_db(monkeypatch):
    monkeypatch.delenv("TASK_DB_URL", raising=False)
    monkeypatch.delenv("DB_INSTANCE_CONNECTION_NAME", raising=False)
    monkeypatch.delenv("DB_HOST", raising=False)
    from common.db import reset_engine_cache

    reset_engine_cache()
    reset_store_cache()
    store = store_for(templates.DEFAULTS)
    assert isinstance(store, PyPromptStore)
    assert store.get(templates.SCENARIOS).version == 0            # 0 = compiled-in default
    assert store.pinned()[templates.SCENARIOS] == 0               # what the run log records


async def test_refresh_is_a_noop_on_the_python_store():
    store = PyPromptStore(templates.DEFAULTS)
    await store.refresh()
    assert store.get(templates.JUDGE_SCENARIOS).body


# --- the rewired prompts still render the same contract ---------------------------------------------
def test_rewired_prompts_render_through_the_store():
    """prompts.py now pulls its body from the store; the computed params (scope block, kinds, focus)
    still come from Python. Assert the seams line up end to end."""
    from common.testplan.llm.prompts import scenarios_prompt
    from common.testplan.models import TestData, TestPlan

    plan = TestPlan(id="p", context_id="run-x", methodology=["api"], metrics=["end-state"])
    plan.scope = ["docs-import zip upload"]
    plan.out_of_scope = ["Agentic-Framework self-check"]
    body = scenarios_prompt(plan, "pack", [TestData(id="td", kind="mock-data")],
                            include_context=False, focus_units=["jira:LUZ-1"])
    assert "In scope (cover ONLY these behaviours): docs-import zip upload" in body
    assert "Agentic-Framework self-check" in body
    assert '{"items": [ ... ]}' in body
    assert "GENERATE ONLY for these pack unit ids" in body
    assert "scenario:run-x:" in body
    assert "$" not in body                                        # nothing left unsubstituted


# --- P6: widened coverage (KGA planners + engine prompts) -------------------------------------
def test_kga_planner_templates_keep_their_json_contract_and_injection_guard():
    """These planners put RAW TICKET TEXT in front of the model, so the untrusted-data fence is a
    security control, not phrasing — a publish must not be able to drop it. Their JSON contract is the
    bare object shape (no output_schema wrapper), so that gets pinned too."""
    from knowledge_gathering.gather.explore.planners import templates as kga

    for key, contract in kga.SCHEMA_CONTRACT.items():
        body = kga.DEFAULTS[key].body
        assert contract in body, f"{key} lost its JSON contract"
        assert kga.INJECTION_GUARD in body, f"{key} lost the untrusted-data fence"
        validate(key, body, kga.DEFAULTS[key].engine, kga.DEFAULTS[key].required_vars)


def test_kga_planner_render_substitutes_the_ticket():
    from knowledge_gathering.gather.explore.planners import templates as kga

    out = kga.render(kga.HYPOTHESIZE, "ZIP import", "imports transfer.zip", ["health"])
    assert "Title: ZIP import" in out and "Labels: health" in out
    assert '{"key_phrases":[...],"entities":[...],"subsystems":[...]}' in out
    assert "$" not in out


def test_engine_questions_template_keeps_the_ARRAY_contract():
    """Opposite of the testplan generators: engine.questions is parsed by `loads_array`, so a bare
    JSON array is CORRECT here. Pinning it stops a well-meaning publish from 'fixing' it to an object
    and silently breaking the parser."""
    from common.llm import templates as engine

    body = engine.DEFAULTS[engine.QUESTIONS].body
    assert "Return ONLY a JSON array" in body
    for key, tpl in engine.DEFAULTS.items():
        validate(key, tpl.body, tpl.engine, tpl.required_vars)


def test_rewired_engine_prompts_render():
    from common.llm.prompts import question_prompt

    class _Pack:
        def summary_text(self):
            return "PACK"

    body = question_prompt(_Pack(), "business", include_context=False)
    assert "ROUND: Business" in body and "Use id prefix 'Q-bus-'" in body
    assert "$" not in body


# --- P7: attributable scores ----------------------------------------------------------------------
def test_compare_runs_attributes_a_score_delta_to_differing_prompt_versions(monkeypatch):
    """The payoff: two runs of one ticket differ for unknown reasons unless you know which prompts
    each ran. Same versions -> variance; different versions -> an experiment."""
    from common.admin import runs

    monkeypatch.setattr(runs, "_prompt_pins",
                        lambda bank, ctx: {"tpd.scenarios": 2 if ctx == "b" else 1})
    monkeypatch.setattr(runs, "_assured_score", lambda bank, ctx: 0.55 if ctx == "b" else 0.34)
    out = "\n".join(runs._prompt_section(None, "a", "b"))
    assert "Prompts differ" in out
    assert "| `tpd.scenarios` | v1 | v2 |" in out
    assert "Higher score: **b**" in out and "+0.210" in out


def test_compare_runs_calls_identical_prompt_versions_variance(monkeypatch):
    from common.admin import runs

    monkeypatch.setattr(runs, "_prompt_pins", lambda bank, ctx: {"tpd.scenarios": 1})
    monkeypatch.setattr(runs, "_assured_score", lambda bank, ctx: 0.34)
    out = "\n".join(runs._prompt_section(None, "a", "b"))
    assert "Identical prompt versions" in out and "model variance" in out


def test_prompt_section_is_absent_for_runs_predating_p7(monkeypatch):
    from common.admin import runs

    monkeypatch.setattr(runs, "_prompt_pins", lambda bank, ctx: {})
    assert runs._prompt_section(None, "a", "b") == []
