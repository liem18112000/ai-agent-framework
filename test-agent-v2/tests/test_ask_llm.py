"""G4 external-LLM lead enumerator (D15) — the `Leads` output_schema + the `LlmAgent` planner.
No live model: a fake ADK `BaseLlm` returns canned structured JSON."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from knowledge_gathering.gather.explore.planners.ask_llm import OUTPUT_KEY, build_leads_agent
from knowledge_gathering.gather.explore.planners.schemas import Leads
from tests.conftest import fake_model, run_planner_agent

# --- P0: the Leads output_schema (strip + dedup + cap that replaced `_coerce_leads`) --------------

def test_as_leads_strips_dedups_and_is_order_stable():
    assert Leads(phrases=["export", " export ", "  ", "audit"]).as_leads() == ["export", "audit"]


def test_as_leads_caps_at_six_by_truncation_not_rejection():
    # The old `ask_llm_leads` truncated; the schema carries NO max_length so an over-long reply
    # still validates and is capped here (never degrades to []).
    leads = Leads(phrases=[f"lead-{i}" for i in range(20)])
    assert leads.as_leads() == [f"lead-{i}" for i in range(6)]


def test_as_leads_empty_is_blank():
    assert Leads().as_leads() == []


def test_schema_rejects_non_json():
    with pytest.raises(ValidationError):
        Leads.model_validate_json("not json at all")


def test_schema_rejects_bare_array():
    # output_schema=Leads expects the OBJECT {"phrases":[...]}, not a bare array → ValidationError.
    with pytest.raises(ValidationError):
        Leads.model_validate_json('["audit log", "bulk export"]')


# --- P1: the leads LlmAgent (fake model → validated dict in session.state[output_key]) ------------

async def test_agent_writes_validated_dict_to_state():
    canned = json.dumps({"phrases": ["restricted folders", "audit log", "bulk export"]})
    model = fake_model(canned)
    agent = build_leads_agent(model=model)
    state = await run_planner_agent(
        agent, {"title": "Export fails for restricted folders", "description": "b",
                "labels": ["earchive"]}, output_key=OUTPUT_KEY)
    assert Leads(**state).as_leads() == ["restricted folders", "audit log", "bulk export"]
    assert len(model.calls) == 1


async def test_agent_empty_object_yields_no_leads():
    model = fake_model("{}")
    agent = build_leads_agent(model=model)
    state = await run_planner_agent(agent, {"title": "t", "description": "", "labels": []},
                                    output_key=OUTPUT_KEY)
    assert Leads(**state).as_leads() == []
