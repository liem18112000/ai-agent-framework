"""Liveness / readiness route builder shared by both agent servers."""

from __future__ import annotations

import os

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


def make_health_routes(
    agent_name: str, agent_version: str, required_env: tuple[str, ...]
) -> list[Route]:
    """Return [/livez, /readyz] routes."""

    async def livez(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    async def readyz(_: Request) -> JSONResponse:
        missing = [k for k in required_env if not os.environ.get(k)]
        if missing:
            return JSONResponse({"status": "not-ready", "missing": missing}, status_code=503)
        return JSONResponse({"status": "ready", "agent": agent_name, "version": agent_version})

    return [
        Route("/livez", livez, methods=["GET"]),
        Route("/readyz", readyz, methods=["GET"]),
    ]
