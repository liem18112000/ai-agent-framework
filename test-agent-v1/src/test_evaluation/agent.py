"""Static A2A definitions — this agent's skills and Agent Card.

Shared card scaffolding (transport / I/O modes / capabilities / bearer security) lives in
common.card; only the skills + name/description/version are agent-specific.
"""

from __future__ import annotations

from a2a.types import AgentSkill

from common.card import build_agent_card, resolve_url
from test_evaluation import __version__

PORT, PUBLIC_URL = resolve_url(8080)

SKILLS = [
    AgentSkill(
        id="evaluate-pack",
        name="Evaluate a knowledge pack",
        description=(
            "Score the pack a gather/refine produced for a context id — retrieval precision/recall "
            "(vs a golden relevant-id set, with a hard-negative leak gate), groundedness rubrics on "
            "the understanding, and entity coverage — into one Pack Quality Score."
        ),
        tags=["evaluation", "pqs", "quality", "ragas", "adk"],
        examples=["evaluate run-6f2a", '{"context_id": "run-6f2a"}'],
    ),
    AgentSkill(
        id="evaluate-plan",
        name="Evaluate a test plan + suite",
        description=(
            "Score the test plan + suite the Test-Plan agent produced for a context id — scope "
            "precision/recall (with a must-not-scope leak gate), coverage adequacy (AC-recall + "
            "coverage-matrix completeness + traceability), oracle strength + fault-class coverage "
            "(the fault-detection proxy), and brief groundedness — into one Test-Plan Score."
        ),
        tags=["evaluation", "tps", "quality", "coverage", "oracle"],
        examples=["evaluate plan run-6f2a", '{"context_id": "run-6f2a"}'],
    ),
]

AGENT_CARD = build_agent_card(
    name="test-evaluation",
    description=(
        "Scores the Testing Agent's knowledge packs into a Pack Quality Score (ADK trajectory + "
        "RAGAS retrieval/generation, mapped to the KGA). Step 5 (EVALUATION) of the Testing Agent, "
        "driven by local Claude over A2A."
    ),
    version=__version__,
    skills=SKILLS,
    url=PUBLIC_URL,
)
