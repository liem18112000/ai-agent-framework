"""A2A -> MCP bridge for the knowledge-gathering agent.

`a2a_client` (the A2A half) has no `mcp` dependency and is importable on its own.
`mcp_server` (the MCP half) requires the optional `mcp` package (`pip install .[bridge]`)
and is imported lazily by `__main__`, so importing this package never forces `mcp`.
"""

from __future__ import annotations

from common.bridge.a2a_client import (
    A2ABridgeClient,
    A2AError,
    A2AResult,
    extract_text,
)

__all__ = ["A2ABridgeClient", "A2AError", "A2AResult", "extract_text"]
