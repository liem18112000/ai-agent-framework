"""TPD ADK A2A app — the v2 replacement for `server.py`.

`uvicorn test_plan_definition.adk_app:app` serves the TPD root agent over A2A (to_a2a), behind the
same bearer + /livez /readyz as v1, reusing v1's AGENT_CARD for exact skill parity (invariant I4).
"""

from __future__ import annotations

from common.adk.serve import serve
from test_plan_definition.a2a_card import AGENT_CARD  # v1 card — exact skills the bridge expects
from test_plan_definition.agent import root_agent

# TPD needs only GCS to be ready (Vertex is optional; unset → heuristic path).
_REQUIRED_ENV = ("GCS_BUCKET",)

app = serve(root_agent, _REQUIRED_ENV, port=8081, agent_card=AGENT_CARD, version=AGENT_CARD.version)
