"""A2A bearer-token enforcement (Starlette middleware) — transport-neutral, wraps main:app (C3/D13).

Fail-CLOSED (SEC-1): when the expected bearer is unset/empty the gate refuses every non-open request
unless `ALLOW_INSECURE=1` opts into the local/dev escape hatch. Compares in constant time (ADK-04)."""

from __future__ import annotations

import hmac
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from common.monitoring import get_logger

log = get_logger("adk.auth")

_warned = False


def is_open_path(path: str) -> bool:
    """Health probes + agent-card discovery are unauthenticated; everything else is gated.

    Exact/prefix match, NOT a loose substring (GW-09b): `/.well-known/…` only as a real prefix."""
    return path in ("/livez", "/readyz") or path.startswith("/.well-known/")


def bearer_ok(token: str | None, authorization: str) -> bool:
    """Fail-CLOSED bearer decision for one request (`token` = the expected secret, may be None/empty).

    token set   → constant-time compare of `authorization` against `Bearer <token>`.
    token empty → permissive ONLY with `ALLOW_INSECURE=1` (local/dev); otherwise fail closed (401),
                  logging an ERROR once so a blank secret in a public deploy is never silent.
    """
    if token:
        return hmac.compare_digest(authorization, f"Bearer {token}")
    if os.environ.get("ALLOW_INSECURE") == "1":
        return True
    global _warned
    if not _warned:
        _warned = True
        log.error("bearer token expected but unset/empty and ALLOW_INSECURE!=1 — refusing all "
                  "non-open requests (fail closed). Set the bearer secret, or ALLOW_INSECURE=1 for dev.")
    return False


class BearerAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not is_open_path(request.url.path) and not bearer_ok(
            os.environ.get("A2A_BEARER_TOKEN"), request.headers.get("authorization", "")
        ):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)
