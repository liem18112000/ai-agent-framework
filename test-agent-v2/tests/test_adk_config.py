"""C1 — model access via the `ModelProvider` registry (Claude-on-Vertex the sole provider; D10/I8)."""

from __future__ import annotations

import pytest

from common.adk import agent_model, get_config, get_provider
from common.adk.providers import VertexClaudeProvider

_VC = "common.adk.providers.vertex_claude.vertex_config"


def test_default_backend_is_claude(monkeypatch):
    monkeypatch.delenv("TESTAGENT_MODEL_BACKEND", raising=False)
    assert get_config().model_backend == "claude"


def test_provider_registry_maps_claude(monkeypatch):
    monkeypatch.delenv("TESTAGENT_MODEL_BACKEND", raising=False)
    prov = get_provider()
    assert isinstance(prov, VertexClaudeProvider) and prov.name == "claude"


def test_unknown_backend_raises(monkeypatch):
    monkeypatch.setenv("TESTAGENT_MODEL_BACKEND", "gemini")
    with pytest.raises(KeyError):
        get_provider()


def test_agent_model_none_without_vertex(monkeypatch):
    monkeypatch.delenv("TESTAGENT_MODEL_BACKEND", raising=False)
    monkeypatch.setattr(_VC, lambda: None)
    assert agent_model() is None


def test_agent_model_litellm_when_configured(monkeypatch):
    monkeypatch.delenv("TESTAGENT_MODEL_BACKEND", raising=False)
    monkeypatch.setattr(_VC, lambda: ("proj", "europe-west6", "claude-sonnet-5"))
    llm = agent_model(max_tokens=1234)
    assert "claude-sonnet-5" in str(getattr(llm, "model", ""))
