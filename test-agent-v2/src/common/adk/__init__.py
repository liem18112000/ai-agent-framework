"""common.adk — the ADK substrate for test-agent-v2 (A.0 shared foundation)."""

from common.adk.config import Config, get_config
from common.adk.interrogation import InterrogationAgent
from common.adk.model import agent_model, complete, model_configured
from common.adk.plugins import LearnDrainPlugin
from common.adk.providers import ModelProvider, get_provider
from common.adk.services import build_runner, build_session_service

__all__ = [
    "Config",
    "InterrogationAgent",
    "LearnDrainPlugin",
    "ModelProvider",
    "agent_model",
    "build_runner",
    "build_session_service",
    "complete",
    "get_config",
    "get_provider",
    "model_configured",
]
