"""Single MCP gateway package — one endpoint fronting the three A2A agents (see `mcp_server`)."""

from __future__ import annotations

from gateway.mcp_server import http_app, mcp

__all__ = ["http_app", "mcp"]
