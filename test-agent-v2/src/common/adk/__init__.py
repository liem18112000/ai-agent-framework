"""common.adk — the ADK substrate for test-agent-v2 (A.0 shared foundation).

Replaces the v1 a2a-sdk shell (server.py / card.py / executor / taskstore) with ADK wiring, while the
framework-neutral engine (memory / learn / interrogate / llm / atlassian / codegraph) is reused as-is.
"""

from common.adk.config import Config, get_config
from common.adk.interrogation import InterrogationAgent
from common.adk.model import agent_model, claude_llm
from common.adk.plugins import LearnDrainPlugin, LessonRecallPlugin
from common.adk.providers import ModelProvider, get_provider
from common.adk.serve import serve
from common.adk.services import build_runner, build_session_service
from common.adk.tools import memory_tools

__all__ = [
    "Config",
    "InterrogationAgent",
    "LearnDrainPlugin",
    "LessonRecallPlugin",
    "ModelProvider",
    "agent_model",
    "build_runner",
    "build_session_service",
    "claude_llm",
    "get_config",
    "get_provider",
    "memory_tools",
    "serve",
]
