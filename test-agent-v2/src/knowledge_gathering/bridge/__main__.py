"""Entry point for the MCP bridge — `python -m knowledge_gathering.bridge`.

Transport is chosen by env `KGA_BRIDGE_TRANSPORT` (default `stdio`):

- **stdio** (default) — a desktop MCP client (Claude Desktop / Claude Code) launches this as a
  local subprocess and pipes stdin/stdout. Cannot be hosted remotely.
- **http** (a.k.a. `streamable-http`) — serves MCP over Streamable HTTP on 0.0.0.0:$PORT at
  `/mcp`, so it can run on Cloud Run and Claude reaches it as a *remote* MCP connector.

Either way it reads KGA_A2A_URL / A2A_BEARER_TOKEN (see mcp_server) and talks A2A to the agent.
"""

from __future__ import annotations

import os

from knowledge_gathering.bridge.mcp_server import http_app, mcp


def main() -> None:
    transport = os.environ.get("KGA_BRIDGE_TRANSPORT", "stdio").lower()
    if transport in ("http", "streamable-http"):
        import uvicorn

        # Run the (optionally bearer-gated) HTTP app ourselves so the auth middleware wraps it.
        # Cloud Run injects $PORT and expects the container to listen on all interfaces.
        uvicorn.run(http_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
