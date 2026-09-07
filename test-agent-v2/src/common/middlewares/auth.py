"""A2A bearer-token enforcement (Starlette middleware).

Card + health endpoints stay open (discovery + probes); everything else requires
`Authorization: Bearer <A2A_BEARER_TOKEN>`. Token read per-request; unset = no
enforcement (dev).
"""

from __future__ import annotations

import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

_OPEN_PREFIXES = ("/.well-known/", "/livez", "/readyz")


class BearerAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        token = os.environ.get("A2A_BEARER_TOKEN")  # unset → no enforcement (dev)
        if (
            token
            and not request.url.path.startswith(_OPEN_PREFIXES)
            and request.headers.get("authorization") != f"Bearer {token}"
        ):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)
