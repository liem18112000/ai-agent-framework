"""Test-Evaluation ADK A2A app — the v2 replacement for `server.py`."""

from __future__ import annotations

from common.adk.serve import serve
from test_evaluation.a2a_card import AGENT_CARD
from test_evaluation.agent import root_agent

_REQUIRED_ENV = ("GCS_BUCKET",)

app = serve(root_agent, _REQUIRED_ENV, port=8081, agent_card=AGENT_CARD, version=AGENT_CARD.version)
