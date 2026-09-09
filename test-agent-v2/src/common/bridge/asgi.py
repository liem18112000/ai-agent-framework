"""Open `/livez` health + inbound bearer auth for a bridge's Streamable-HTTP endpoint."""

from __future__ import annotations

import os


class _BearerASGIMiddleware:
    """Open `/livez` health + optional inbound-bearer gate for a bridge's Streamable-HTTP endpoint."""

    def __init__(self, app, token: str | None) -> None:
        self.app, self.token = app, token

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http":
            if scope.get("path", "") == "/livez":
                await send({"type": "http.response.start", "status": 200,
                            "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body", "body": b'{"status":"ok"}'})
                return
            got = dict(scope["headers"]).get(b"authorization", b"").decode()
            if self.token and got != f"Bearer {self.token}":
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body", "body": b'{"error":"unauthorized"}'})
                return
        await self.app(scope, receive, send)


def build_http_app(mcp, env_prefix: str):
    """Streamable-HTTP ASGI app for a bridge's `mcp` — open `/livez` + `<env_prefix>_BEARER_TOKEN` gate."""
    from mcp.server.transport_security import TransportSecuritySettings

    stateless = os.environ.get(f"{env_prefix}_STATELESS", "").lower() in ("1", "true", "yes", "on")
    hosts = [h.strip() for h in os.environ.get(f"{env_prefix}_ALLOWED_HOSTS", "").split(",") if h.strip()]
    sec = (
        TransportSecuritySettings(allowed_hosts=hosts, allowed_origins=["*"])
        if hosts
        else TransportSecuritySettings(
            enable_dns_rebinding_protection=False, allowed_hosts=[], allowed_origins=[]
        )
    )
    app = mcp.streamable_http_app(stateless_http=stateless, transport_security=sec)
    return _BearerASGIMiddleware(app, os.environ.get(f"{env_prefix}_BEARER_TOKEN"))
