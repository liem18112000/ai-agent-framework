"""Inbound bearer auth for a bridge's Streamable-HTTP endpoint (shared by both bridges)."""

from __future__ import annotations

import os


class _BearerASGIMiddleware:
    """Bearer gate for a bridge's Streamable-HTTP endpoint.

    Pure ASGI on purpose — NOT Starlette's BaseHTTPMiddleware, which buffers responses
    and would break the MCP SSE stream. Unauthorized HTTP requests are rejected with 401
    before reaching the app; authorized ones (and non-HTTP scopes like lifespan) pass
    through untouched.
    """

    def __init__(self, app, token: str) -> None:
        self.app, self.token = app, token

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http":
            got = dict(scope["headers"]).get(b"authorization", b"").decode()
            if got != f"Bearer {self.token}":
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body", "body": b'{"error":"unauthorized"}'})
                return
        await self.app(scope, receive, send)


def build_http_app(mcp, env_prefix: str):
    """Streamable-HTTP ASGI app for a bridge's `mcp`, gated by `<env_prefix>_BEARER_TOKEN`.

    Shared by both bridges (env_prefix = "KGA_BRIDGE" / "TPD_BRIDGE"). Env is read here (not at
    import) so it's configurable just before serving and testable. Reads:
      <PREFIX>_STATELESS      run the MCP HTTP transport statelessly
      <PREFIX>_ALLOWED_HOSTS  comma-list for the SDK's DNS-rebinding guard; if empty the guard is
                              disabled (safe: a public run.app domain gated by the bearer below,
                              not a browser-reachable localhost)
      <PREFIX>_BEARER_TOKEN   unset = open (dev); set = every HTTP request needs Bearer <it>
    """
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
    token = os.environ.get(f"{env_prefix}_BEARER_TOKEN")
    return _BearerASGIMiddleware(app, token) if token else app
