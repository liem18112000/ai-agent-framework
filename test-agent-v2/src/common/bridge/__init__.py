"""Shared A2A -> MCP bridge pieces."""

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
