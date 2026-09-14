"""Single A2A entrypoint — one agent per container, selected by $AGENT. Run: `uvicorn main:app`.

Replaces the per-package adk_app.py + common.adk.serve: build the production Runner (Cloud SQL
session + GCS artifacts + the self-learning plugins), expose the agent over native ADK A2A
(to_a2a, mounted at `/`), add /livez /readyz, and gate everything behind A2A_BEARER_TOKEN.
"""

from __future__ import annotations

import importlib
import os

from google.adk.a2a.utils.agent_to_a2a import to_a2a
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from common.adk.auth import BearerAuthMiddleware
from common.adk.services import build_runner, build_task_store

_AGENT = os.environ.get("AGENT", "knowledge_gathering")
_ATLASSIAN = ("ATLASSIAN_BASE_URL", "ATLASSIAN_EMAIL", "ATLASSIAN_API_TOKEN", "GCS_BUCKET")
_REQUIRED_ENV = {"knowledge_gathering": _ATLASSIAN, "testing_agent": _ATLASSIAN}


def _health_routes(name: str, required: tuple[str, ...]) -> list[Route]:
    async def livez(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    async def readyz(_: Request) -> JSONResponse:
        missing = [k for k in required if not os.environ.get(k)]
        if missing:
            return JSONResponse({"status": "not-ready", "missing": missing}, status_code=503)
        return JSONResponse({"status": "ready", "agent": name})

    return [Route("/livez", livez, methods=["GET"]), Route("/readyz", readyz, methods=["GET"])]


def build_app(module: str = _AGENT):
    root = importlib.import_module(f"{module}.agent").root_agent
    app = to_a2a(root, runner=build_runner(root, app_name=root.name), task_store=build_task_store())
    app.router.routes.extend(_health_routes(root.name, _REQUIRED_ENV.get(module, ("GCS_BUCKET",))))
    app.add_middleware(BearerAuthMiddleware)
    return app


app = build_app()
