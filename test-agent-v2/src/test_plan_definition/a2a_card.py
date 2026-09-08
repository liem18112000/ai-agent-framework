"""Static A2A definitions — this agent's skills and Agent Card."""

from __future__ import annotations

from a2a.types import AgentSkill

from common.card import build_agent_card, resolve_url
from test_plan_definition import __version__

PORT, PUBLIC_URL = resolve_url(8081)

SKILLS = [
    AgentSkill(
        id="define-test-plan",
        name="Define the test plan (interrogate + confirm)",
        description=(
            "Step 3 of the Testing Agent. Turn an approved insight pack (from knowledge_gathering) "
            "into a confirmed Test Plan over a multi-turn A2A dialogue: rank methodology / scope / "
            "metrics questions, ingest human answers, distill each into a provenance-carrying plan "
            "decision, and restate a plan brief the human reconfirms."
        ),
        tags=["test-plan", "define", "interrogate", "human-in-the-loop"],
        examples=[
            "Define the test plan for context run-6f2a",
            '{"context_id": "run-6f2a", "rounds": ["methodology", "scope", "metrics"]}',
        ],
    ),
    AgentSkill(
        id="implement-test-plan",
        name="Implement the confirmed test plan",
        description=(
            "Step 4 of the Testing Agent. From a confirmed Test Plan + insight pack, generate the "
            "test data (mock data, test accounts), scenarios (happy + negative), and step-by-step "
            "test steps, and persist them to the shared memory bank."
        ),
        tags=["test-plan", "implement", "scenarios", "test-data", "memory"],
        examples=["Implement the test plan for context run-6f2a"],
    ),
    AgentSkill(
        id="get-test-plan",
        name="Read the confirmed/draft test plan",
        description="Return the current Test Plan brief for a context id (read-only).",
        tags=["test-plan", "read"],
    ),
    AgentSkill(
        id="get-scenarios",
        name="Read the generated scenarios",
        description="Return the generated test scenarios/steps for a context id (read-only).",
        tags=["test-plan", "read"],
    ),
]

AGENT_CARD = build_agent_card(
    name="test-plan-definition",
    description=(
        "Turns an approved insight pack into a confirmed Test Plan (define) and its test "
        "data / scenarios / steps (implement). Step 3+4 of the Testing Agent, driven by local "
        "Claude over A2A, on the shared GCS memory bank."
    ),
    version=__version__,
    skills=SKILLS,
    url=PUBLIC_URL,
)
