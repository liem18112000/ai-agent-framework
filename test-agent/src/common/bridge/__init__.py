"""Shared A2A -> MCP bridge pieces.

`a2a_client` (the A2A half) has no `mcp` dependency and is importable on its own.
`asgi` holds the bearer gate reused by both agents' MCP servers. `prompts` holds the
shared trigger instructions + `test` prompt.
"""

from __future__ import annotations

from common.bridge.a2a_client import (
    A2ABridgeClient,
    A2AError,
    A2AResult,
    extract_text,
)
from common.bridge.asgi import build_http_app
from common.bridge.session import BridgeSession

__all__ = [
    "A2ABridgeClient",
    "A2AError",
    "A2AResult",
    "BridgeSession",
    "build_http_app",
    "extract_text",
]
