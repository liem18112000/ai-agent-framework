"""A2A -> MCP bridge for the test-plan-definition agent.

The A2A client is generic, so it is reused verbatim from knowledge_gathering.bridge rather
than duplicated. `mcp_server` (the MCP half) needs the optional `mcp` package and is imported
lazily by `__main__`, so importing this package never forces `mcp`.
"""

from __future__ import annotations

from common.bridge.a2a_client import (
    A2ABridgeClient,
    A2AError,
    A2AResult,
    extract_text,
)

__all__ = ["A2ABridgeClient", "A2AError", "A2AResult", "extract_text"]
