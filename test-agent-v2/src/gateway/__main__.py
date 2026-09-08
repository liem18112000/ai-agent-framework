"""Entry point for the single MCP gateway — `python -m gateway`.

Transport via env `GATEWAY_TRANSPORT` (default `stdio`):
- **stdio** — a desktop MCP client launches this as a local subprocess (stdin/stdout).
- **http** — serves MCP over Streamable HTTP on 0.0.0.0:$PORT at `/mcp` (Cloud Run; remote connector).

Either way it reads KGA_A2A_URL / TPD_A2A_URL / TEV_A2A_URL + A2A_BEARER_TOKEN and talks A2A to the
three agents (see mcp_server).
"""

from __future__ import annotations

import os

from gateway.mcp_server import http_app, mcp


def main() -> None:
    transport = os.environ.get("GATEWAY_TRANSPORT", "stdio").lower()
    if transport in ("http", "streamable-http"):
        import uvicorn

        uvicorn.run(http_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
