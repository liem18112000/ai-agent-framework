"""Liveness / readiness route builder shared by both agent servers.

Each agent's ops.py calls make_health_routes with its own agent name/version and the env keys
it needs before it's ready; the /livez + /readyz behaviour is identical, so it lives here.
"""

from __future__ import annotations

import os

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


def make_health_routes(
    agent_name: str, agent_version: str, required_env: tuple[str, ...]
) -> list[Route]:
    """Return [/livez, /readyz] routes.

    /livez always 200 (the process is up). Path is /livez NOT /healthz: the Google Front End
    reserves /healthz on Cloud Run and 404s it before it reaches the container.
    /readyz returns 200 when every key in `required_env` is set, else 503 listing the gaps.
    """

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
