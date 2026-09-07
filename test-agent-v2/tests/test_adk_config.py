"""E2 — the Config model-backend switch (Claude-via-LiteLlm default | Gemini-native)."""

from __future__ import annotations

from common.adk import agent_model, get_config


def test_default_backend_is_claude(monkeypatch):
    monkeypatch.delenv("TESTAGENT_MODEL_BACKEND", raising=False)
    assert get_config().model_backend == "claude"


def test_gemini_backend_via_env(monkeypatch):
    monkeypatch.setenv("TESTAGENT_MODEL_BACKEND", "gemini")
    monkeypatch.setenv("TESTAGENT_GEMINI_MODEL", "gemini-2.5-pro")
    assert get_config().model_backend == "gemini"
    assert agent_model() == "gemini-2.5-pro"  # ADK LlmAgent takes the Gemini model-id string


def test_agent_model_claude_none_without_vertex(monkeypatch):
    monkeypatch.setenv("TESTAGENT_MODEL_BACKEND", "claude")
    monkeypatch.setattr("common.adk.model.vertex_config", lambda: None)
    assert agent_model() is None  # no Vertex → caller uses the heuristic path (I7)


def test_agent_model_claude_litellm_when_configured(monkeypatch):
    monkeypatch.setenv("TESTAGENT_MODEL_BACKEND", "claude")
    monkeypatch.setattr("common.adk.model.vertex_config",
                        lambda: ("proj", "europe-west6", "claude-sonnet-5"))
    llm = agent_model(max_tokens=1234)
    assert "claude-sonnet-5" in str(getattr(llm, "model", ""))
