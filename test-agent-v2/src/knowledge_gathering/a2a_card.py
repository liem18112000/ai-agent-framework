"""Static A2A definitions — this agent's skills and Agent Card."""

from __future__ import annotations

from a2a.types import AgentSkill

from common.card import build_agent_card, resolve_url
from knowledge_gathering import __version__

PORT, PUBLIC_URL = resolve_url(8080)

SKILLS = [
    AgentSkill(
        id="gather-knowledge",
        name="Gather knowledge from a seed",
        description=(
            "Crawl a Jira issue / Confluence page read-only, extract and follow links "
            "within a budget, and distill the result into the GCS markdown memory bank."
        ),
        tags=["atlassian", "jira", "confluence", "crawl", "memory"],
        examples=[
            "Gather knowledge for LUZ-158390 at depth 2",
            '{"seed": "LUZ-158390", "depth": 2}',
        ],
    ),
    AgentSkill(
        id="search-memory",
        name="Search the memory bank",
        description="Query the knowledge index (link graph) in the GCS memory bank.",
        tags=["memory", "read"],
    ),
    AgentSkill(
        id="get-note",
        name="Fetch one memory note",
        description="Return a single distilled note from the GCS memory bank by id.",
        tags=["memory", "read"],
    ),
    AgentSkill(
        id="refine-knowledge",
        name="Refine gathered knowledge (interrogate + confirm)",
        description=(
            "Step 2 of the Testing Agent. Turn a grounded context pack (from gather-knowledge) "
            "into a ranked business/technical/QA question set, ingest human answers over a "
            "multi-turn A2A dialogue, distill each answer into a provenance-carrying insight note "
            "in the memory bank, and restate a confirmed understanding. Re-seeds gathering on gaps."
        ),
        tags=["refine", "interrogate", "insight", "memory", "human-in-the-loop"],
        examples=[
            "Refine knowledge for context run-6f2a",
            '{"context_id": "run-6f2a", "rounds": ["business", "technical", "qa"]}',
        ],
    ),
    AgentSkill(
        id="get-questions",
        name="Read the current refinement question set",
        description="Return the open/answered questions for a refine session by context id.",
        tags=["refine", "read"],
    ),
    AgentSkill(
        id="get-understanding",
        name="Read the refined understanding brief",
        description="Return the latest restated understanding brief for a refine session.",
        tags=["refine", "read"],
    ),
]

AGENT_CARD = build_agent_card(
    name="knowledge-gathering",
    description=(
        "Read-only Atlassian knowledge crawler with a GCS markdown memory bank. "
        "Step 1 (KNOWLEDGE) of the Testing Agent, driven by local Claude over A2A."
    ),
    version=__version__,
    skills=SKILLS,
    url=PUBLIC_URL,
)
