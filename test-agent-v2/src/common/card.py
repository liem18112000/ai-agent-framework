"""Shared A2A AgentCard scaffolding for both agents."""

from __future__ import annotations

import os

from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill, a2a_pb2
from a2a.utils import TransportProtocol


def resolve_url(default_port: int) -> tuple[int, str]:
    """(PORT, PUBLIC_URL) from env, with the agent's default port."""
    port = int(os.environ.get("PORT", str(default_port)))
    return port, os.environ.get("PUBLIC_URL", f"http://localhost:{port}/")


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
    """An AgentCard with the transport / I/O modes / capabilities / security shared by both agents."""
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
