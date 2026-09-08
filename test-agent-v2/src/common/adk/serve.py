"""`serve()` — expose an ADK agent over A2A behind the SAME bearer + health as v1."""

from __future__ import annotations

from common.adk.services import build_runner
from common.middlewares import BearerAuthMiddleware
from common.monitoring import get_logger
from common.ops import make_health_routes

log = get_logger("adk.serve")


def serve(root_agent, required_env: tuple[str, ...], *, port: int = 8081,
          app_name: str | None = None, agent_card=None, version: str = "0.2.0"):
    """Return a Starlette A2A app for `root_agent`, with /livez /readyz and bearer auth."""
    from google.adk.a2a.utils.agent_to_a2a import to_a2a

    name = app_name or root_agent.name
    runner = build_runner(root_agent, app_name=name)
    app = to_a2a(root_agent, port=port, runner=runner, agent_card=agent_card)
    app.router.routes.extend(make_health_routes(name, version, required_env))
    app.add_middleware(BearerAuthMiddleware)
    log.info("serving A2A (ADK) for %s on :%d", name, port)
    return app
