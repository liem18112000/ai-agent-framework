"""G2 hypothesize step (D15) — the `Hypothesis` output_schema + the `LlmAgent` planner + its wiring
into the ADK GatherAgent. No live model: a fake ADK `BaseLlm` returns canned structured JSON."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from knowledge_gathering.gather.explore.planners.hypothesize import (
    OUTPUT_KEY,
    build_hypothesize_agent,
)
from knowledge_gathering.gather.explore.planners.schemas import Hypothesis
from tests.conftest import drive_gather_agent, fake_model, run_planner_agent
from tests.eval.harness import recorded_client, run_gather_offline

# --- P0: the Hypothesis output_schema (dedup + cap logic that replaced `_coerce_terms`) -----------

def test_as_terms_unions_fields_in_order():
    h = Hypothesis(key_phrases=["restricted folder export"], entities=["Folder", "Document"],
                   subsystems=["luz-docs", "export"])
    # Byte-for-byte the string the old `_coerce_terms` + `" ".join(...)` produced → same focus,
    # so the downstream promotions are identical (flag-on parity, §8).
    assert h.as_terms() == "restricted folder export Folder Document luz-docs export"


def test_as_terms_dedups_and_is_order_stable():
    h = Hypothesis(key_phrases=["export", "export"], entities=["Folder"], subsystems=["export"])
    assert h.as_terms() == "export Folder"


def test_as_terms_caps_at_eight():
    h = Hypothesis(key_phrases=[f"t{i}" for i in range(20)])
    assert h.as_terms() == "t0 t1 t2 t3 t4 t5 t6 t7"


def test_as_terms_empty_is_blank():
    assert Hypothesis().as_terms() == ""


def test_schema_rejects_non_json():
    # ADK validates the model reply the same way; malformed JSON → ValidationError (→ degrade).
    with pytest.raises(ValidationError):
        Hypothesis.model_validate_json("not json at all")


# --- P1: the hypothesize LlmAgent (fake model → validated dict in session.state[output_key]) ------

async def test_agent_writes_validated_dict_to_state():
    canned = json.dumps({"key_phrases": ["restricted folder export"],
                         "entities": ["Folder", "Document"],
                         "subsystems": ["luz-docs", "export"]})
    model = fake_model(canned)
    agent = build_hypothesize_agent(model=model)
    state = await run_planner_agent(
        agent, {"title": "Export fails for restricted folders", "description": "b",
                "labels": ["earchive"]}, output_key=OUTPUT_KEY)
    assert Hypothesis(**state).as_terms() == "restricted folder export Folder Document luz-docs export"
    assert len(model.calls) == 1


async def test_agent_empty_object_yields_no_terms():
    model = fake_model("{}")
    agent = build_hypothesize_agent(model=model)
    state = await run_planner_agent(agent, {"title": "t", "description": "", "labels": []},
                                    output_key=OUTPUT_KEY)
    assert Hypothesis(**state).as_terms() == ""


# --- P3: the GatherAgent always drives the hypothesize planner (D15) ------------------------------

async def test_flag_on_enriched_focus_reaches_reply(monkeypatch):
    canned = json.dumps({"key_phrases": ["invoice charge job"], "entities": ["luz_finance"],
                         "subsystems": []})
    model = fake_model(canned)
    reply, _bank = await drive_gather_agent(
        "LUZ-501", monkeypatch, client=recorded_client("eval_rich"), hyp_model=model)
    assert "Gather complete" in reply
    assert model.calls and len(model.calls) == 1
    assert "Hypothesized focus: invoice charge job luz_finance" in reply


async def test_flag_on_empty_hyp_keeps_probe_terms(monkeypatch):
    model = fake_model("{}")                        # valid but empty → as_terms() == ""
    reply, _bank = await drive_gather_agent(
        "LUZ-501", monkeypatch, client=recorded_client("eval_rich"), hyp_model=model)
    assert "Gather complete" in reply
    assert len(model.calls) == 1
    assert "Hypothesized focus" not in reply        # kept probe terms, no enrichment block


async def test_flag_on_junk_reply_degrades_and_gathers(monkeypatch):
    # §8 gate: a malformed reply fails output_schema validation → GatherAgent degrades to probe.terms.
    model = fake_model("not json at all")
    reply, bank = await drive_gather_agent(
        "LUZ-501", monkeypatch, client=recorded_client("eval_rich"), hyp_model=model)
    assert "Gather complete" in reply
    assert len(model.calls) == 1
    assert "Hypothesized focus" not in reply
    # degraded path persists the SAME nodes as an explore gather whose hypothesize simply no-ops
    # (both reduce to probe.terms) — compare at the same `explore` setting so web-follow parity holds
    baseline = run_gather_offline("LUZ-501", client=recorded_client("eval_rich"),
                                  text="gather LUZ-501 explore")
    graph, _ = bank.load_index()
    assert set(graph.nodes.keys()) == baseline.node_ids
