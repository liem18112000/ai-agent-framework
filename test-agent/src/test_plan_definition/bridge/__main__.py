"""Entry point for the MCP bridge — `python -m test_plan_definition.bridge`.

Transport is chosen by env `TPD_BRIDGE_TRANSPORT` (default `stdio`):

- **stdio** (default) — a desktop MCP client (Claude Desktop / Claude Code) launches this as a
  local subprocess and pipes stdin/stdout.
- **http** (a.k.a. `streamable-http`) — serves MCP over Streamable HTTP on 0.0.0.0:$PORT at
  `/mcp`, so it can run on Cloud Run as a remote connector.

Either way it reads TPD_A2A_URL / A2A_BEARER_TOKEN (see mcp_server) and talks A2A to the agent.
"""

from __future__ import annotations

import os

from test_plan_definition.bridge.mcp_server import http_app, mcp


def main() -> None:
    transport = os.environ.get("TPD_BRIDGE_TRANSPORT", "stdio").lower()
    if transport in ("http", "streamable-http"):
        import uvicorn

        uvicorn.run(http_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
