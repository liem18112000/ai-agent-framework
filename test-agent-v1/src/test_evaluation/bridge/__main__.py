"""Entry point for the MCP bridge — `python -m test_evaluation.bridge`.

Transport is chosen by env `TEV_BRIDGE_TRANSPORT` (default `stdio`): `stdio` for a local desktop
MCP client, or `http`/`streamable-http` to serve MCP on 0.0.0.0:$PORT at `/mcp` (Cloud Run). Either
way it reads TEV_A2A_URL / A2A_BEARER_TOKEN (see mcp_server) and talks A2A to the agent.
"""

from __future__ import annotations

import os

from test_evaluation.bridge.mcp_server import http_app, mcp


def main() -> None:
    transport = os.environ.get("TEV_BRIDGE_TRANSPORT", "stdio").lower()
    if transport in ("http", "streamable-http"):
        import uvicorn

        uvicorn.run(http_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
