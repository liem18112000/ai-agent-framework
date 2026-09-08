"""G4 external-LLM lead enumerator — `ask_llm_leads` (unit)."""

from __future__ import annotations

import json

import pytest

from knowledge_gathering.explore import ask_llm as al


@pytest.fixture
def vertex_on(monkeypatch):
    """Flag ON + Vertex configured — the state in which the single LLM call actually fires."""
    monkeypatch.setenv("KGA_LLM_LEADS", "1")
    monkeypatch.setenv("VERTEX_PROJECT", "p")
    monkeypatch.setenv("VERTEX_LOCATION", "us-east5")
    monkeypatch.setenv("VERTEX_MODEL", "claude-sonnet-5")


def test_returns_lead_list_from_json_array(vertex_on, monkeypatch):
    canned = json.dumps(["restricted folders", "audit log", "bulk export"])
    monkeypatch.setattr(al, "complete", lambda *a, **k: canned)
    out = al.ask_llm_leads("Export fails for restricted folders", "a body", ["earchive"])
    assert out == ["restricted folders", "audit log", "bulk export"]


def test_dedup_and_strip_and_coerce_non_string(vertex_on, monkeypatch):
    canned = json.dumps(["export", " export ", "  ", "audit", None, 42])
    monkeypatch.setattr(al, "complete", lambda *a, **k: canned)
    assert al.ask_llm_leads("t") == ["export", "audit", "42"]


def test_tolerates_json_code_fence(vertex_on, monkeypatch):
    monkeypatch.setattr(al, "complete", lambda *a, **k: '```json\n["folders", "export"]\n```')
    assert al.ask_llm_leads("t") == ["folders", "export"]


@pytest.mark.parametrize("bad", [
    "not json at all", "{}", '{"leads":["x"]}', '"just a string"', "42", "[]", "",
])
def test_malformed_or_non_array_returns_empty(vertex_on, monkeypatch, bad):
    monkeypatch.setattr(al, "complete", lambda *a, **k: bad)
    assert al.ask_llm_leads("Export fails") == []


def test_caps_at_max_leads(vertex_on, monkeypatch):
    canned = json.dumps([f"lead-{i}" for i in range(20)])
    monkeypatch.setattr(al, "complete", lambda *a, **k: canned)
    out = al.ask_llm_leads("t")
    assert len(out) == al._MAX_LEADS == 6
    assert out == [f"lead-{i}" for i in range(6)]


def test_llm_raises_returns_empty_never_propagates(vertex_on, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("vertex down")

    monkeypatch.setattr(al, "complete", boom)
    assert al.ask_llm_leads("Export fails") == []


def test_flag_off_returns_empty_without_calling_llm(monkeypatch):
    monkeypatch.delenv("KGA_LLM_LEADS", raising=False)
    for k in ("VERTEX_PROJECT", "VERTEX_LOCATION", "VERTEX_MODEL"):
        monkeypatch.setenv(k, "x")
    calls = {"n": 0}

    def spy(*a, **k):
        calls["n"] += 1
        return "[]"

    monkeypatch.setattr(al, "complete", spy)
    assert al.ask_llm_leads("Export fails") == []
    assert calls["n"] == 0


def test_empty_title_returns_empty_without_calling_llm(vertex_on, monkeypatch):
    calls = {"n": 0}

    def spy(*a, **k):
        calls["n"] += 1
        return "[]"

    monkeypatch.setattr(al, "complete", spy)
    assert al.ask_llm_leads("   ") == []
    assert calls["n"] == 0


def test_vertex_unconfigured_returns_empty_without_calling_llm(monkeypatch):
    monkeypatch.setenv("KGA_LLM_LEADS", "1")
    for k in ("VERTEX_PROJECT", "VERTEX_LOCATION", "VERTEX_MODEL"):
        monkeypatch.delenv(k, raising=False)
    calls = {"n": 0}

    def spy(*a, **k):
        calls["n"] += 1
        return "[]"

    monkeypatch.setattr(al, "complete", spy)
    assert al.ask_llm_leads("Export fails") == []
    assert calls["n"] == 0
