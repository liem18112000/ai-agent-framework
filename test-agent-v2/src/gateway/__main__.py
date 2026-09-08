"""Entry point for the single MCP gateway — `python -m gateway`."""

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
