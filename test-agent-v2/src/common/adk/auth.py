"""A2A bearer-token enforcement (Starlette middleware) — transport-neutral, wraps main:app (C3/D13)."""

from __future__ import annotations

import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


def _is_open(path: str) -> bool:
    return path.startswith(("/livez", "/readyz")) or "/.well-known/" in path


class BearerAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        token = os.environ.get("A2A_BEARER_TOKEN")
        if token and not _is_open(request.url.path) and request.headers.get("authorization") != f"Bearer {token}":
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)
