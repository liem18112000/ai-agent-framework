"""KGA ADK A2A app — the v2 replacement for `server.py`."""

from __future__ import annotations

from common.adk.serve import serve
from knowledge_gathering.a2a_card import AGENT_CARD
from knowledge_gathering.agent import root_agent

_REQUIRED_ENV = ("ATLASSIAN_BASE_URL", "ATLASSIAN_EMAIL", "ATLASSIAN_API_TOKEN", "GCS_BUCKET")

app = serve(root_agent, _REQUIRED_ENV, agent_card=AGENT_CARD, version=AGENT_CARD.version)
