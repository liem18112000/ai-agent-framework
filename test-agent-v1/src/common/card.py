"""Shared A2A AgentCard scaffolding for both agents.

Each agent's `agent.py` differs only in name / description / version / skills / port; the
transport binding, I/O modes, streaming capability, and bearer security are identical. Those
shared parts live here so the per-agent modules carry only what is actually agent-specific.

a2a-sdk 1.x: `a2a.types.*` are protobuf messages (proto field names are snake_case), and the
endpoint lives in `supported_interfaces`, not a top-level `url`.
"""

from __future__ import annotations

import os

from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill, a2a_pb2
from a2a.utils import TransportProtocol


def resolve_url(default_port: int) -> tuple[int, str]:
    """(PORT, PUBLIC_URL) from env, with the agent's default port.

    PORT is what the server binds; PUBLIC_URL is what the card advertises (set it to the
    Cloud Run service URL in production; it falls back to http://localhost:PORT/ locally).
    """
    port = int(os.environ.get("PORT", str(default_port)))
    return port, os.environ.get("PUBLIC_URL", f"http://localhost:{port}/")


# Both agents enforce the same opaque-bearer scheme (see each server's BearerAuthMiddleware).
_BEARER_SCHEMES = {
    "bearer": a2a_pb2.SecurityScheme(
        http_auth_security_scheme=a2a_pb2.HTTPAuthSecurityScheme(
            scheme="bearer", bearer_format="opaque"
        )
    )
}
_BEARER_REQUIREMENTS = [
    a2a_pb2.SecurityRequirement(schemes={"bearer": a2a_pb2.StringList(list=[])})
]


def build_agent_card(
    *,
    name: str,
    description: str,
    version: str,
    skills: list[AgentSkill],
    url: str,
) -> AgentCard:
    """An AgentCard with the transport / I/O modes / capabilities / security shared by both agents.

    Only name, description, version, skills, and the advertised url are per-agent.
    """
    return AgentCard(
        name=name,
        description=description,
        version=version,
        supported_interfaces=[
            AgentInterface(url=url, protocol_binding=TransportProtocol.JSONRPC),
        ],
        default_input_modes=["text/plain", "application/json"],
        default_output_modes=["application/json", "text/markdown"],
        capabilities=AgentCapabilities(streaming=True),
        skills=skills,
        security_schemes=_BEARER_SCHEMES,
        security_requirements=_BEARER_REQUIREMENTS,
    )
