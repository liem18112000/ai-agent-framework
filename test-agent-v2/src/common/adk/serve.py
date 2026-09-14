"""The A2A serving seam — the single place `to_a2a` (a2a-sdk, via ADK) turns a root agent into an
ASGI app: the native A2A JSON-RPC routes + agent card, the production Runner, the durable task store,
health probes, and bearer auth.

All server-side dependence on the A2A transport lives HERE (plus `common/bridge/a2a_client.py` for the
client half). Swapping a2a-sdk for another agent transport is a rewrite of this file, not of `main.py`
or any agent. `main.py` only resolves $AGENT → its root_agent and calls `build_agent_app`.
"""

from __future__ import annotations

import os

from google.adk.a2a.utils.agent_to_a2a import to_a2a
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from common.adk.auth import BearerAuthMiddleware
from common.adk.services import build_runner, build_task_store


def _health_routes(name: str, required: tuple[str, ...]) -> list[Route]:
    async def livez(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    async def readyz(_: Request) -> JSONResponse:
        missing = [k for k in required if not os.environ.get(k)]
        if missing:
            return JSONResponse({"status": "not-ready", "missing": missing}, status_code=503)
        return JSONResponse({"status": "ready", "agent": name})

    return [Route("/livez", livez, methods=["GET"]), Route("/readyz", readyz, methods=["GET"])]


def build_agent_app(root, *, required_env: tuple[str, ...]):
    """The A2A ASGI app for `root`: `to_a2a` (Runner + durable task store) + /livez /readyz + bearer auth."""
    app = to_a2a(root, runner=build_runner(root, app_name=root.name), task_store=build_task_store())
    app.router.routes.extend(_health_routes(root.name, required_env))
    app.add_middleware(BearerAuthMiddleware)
    return app
