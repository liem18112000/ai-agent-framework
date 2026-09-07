"""KGA ADK A2A app — the v2 replacement for `server.py`.

`uvicorn knowledge_gathering.adk_app:app` serves the KGA root agent over A2A (to_a2a), behind the
same bearer + /livez /readyz as v1, reusing v1's AGENT_CARD for exact skill parity (invariant I4).
"""

from __future__ import annotations

from common.adk.serve import serve
from knowledge_gathering.a2a_card import AGENT_CARD  # v1 card — exact skills the bridge expects
from knowledge_gathering.agent import root_agent

# The crawler's readiness gate — same env as v1's server.
_REQUIRED_ENV = ("ATLASSIAN_BASE_URL", "ATLASSIAN_EMAIL", "ATLASSIAN_API_TOKEN", "GCS_BUCKET")

app = serve(root_agent, _REQUIRED_ENV, agent_card=AGENT_CARD, version=AGENT_CARD.version)
