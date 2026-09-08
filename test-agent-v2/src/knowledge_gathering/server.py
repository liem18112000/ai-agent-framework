from __future__ import annotations

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.utils import DEFAULT_RPC_URL
from fastapi import FastAPI

from common.middlewares import BearerAuthMiddleware
from common.ops import make_health_routes
from common.taskstore import build_task_store
from knowledge_gathering import __version__
from knowledge_gathering.a2a_card import AGENT_CARD, PORT
from knowledge_gathering.executor import KnowledgeGatheringExecutor
from knowledge_gathering.monitoring import configure, get_logger

configure()
log = get_logger("server")

_REQUIRED_ENV = ("ATLASSIAN_BASE_URL", "ATLASSIAN_EMAIL", "ATLASSIAN_API_TOKEN", "GCS_BUCKET")
health_routes = make_health_routes(AGENT_CARD.name, AGENT_CARD.version, _REQUIRED_ENV)

_handler = DefaultRequestHandler(
    agent_executor=KnowledgeGatheringExecutor(),
    task_store=build_task_store(),
    agent_card=AGENT_CARD,
)

app = FastAPI(
    title=AGENT_CARD.name,
    version=__version__,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.router.routes.extend(
    health_routes
    + create_agent_card_routes(AGENT_CARD)
    + create_jsonrpc_routes(_handler, DEFAULT_RPC_URL, enable_v0_3_compat=True)
)
app.add_middleware(BearerAuthMiddleware)
log.info("%s v%s ready — %d skills, %d routes", AGENT_CARD.name, __version__, len(AGENT_CARD.skills), len(app.router.routes))


def main() -> None:
    import uvicorn

    log.info("serving A2A on 0.0.0.0:%d", PORT)
    uvicorn.run(app, host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()
