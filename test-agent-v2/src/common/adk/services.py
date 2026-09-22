"""ADK Runner + services, wired to the shared runtime."""

from __future__ import annotations

import os

from common.db import get_engine
from common.monitoring import get_logger

log = get_logger("adk.services")


def build_session_service():
    engine = get_engine()
    if engine is None:
        from google.adk.sessions import InMemorySessionService

        log.info("session service: in-memory (no DB configured)")
        return InMemorySessionService()

    from google.adk.sessions import DatabaseSessionService

    log.info("session service: DatabaseSessionService on the shared Cloud SQL engine")
    return DatabaseSessionService(db_engine=engine)


def build_task_store():
    """The A2A TaskStore for `to_a2a` — Postgres-backed on the shared Cloud SQL engine, or None so
    `to_a2a` falls back to its own in-memory store.

    This is SEPARATE from `build_session_service`: `to_a2a` persists ADK session state through the
    runner's SessionService AND the A2A task-lifecycle state through this task_store. Wiring only the
    runner (as before) left the task store in-memory even with Cloud SQL fully configured — task state
    was lost on redeploy/scale. Shares the one cached engine, so both stores use a single pool."""
    engine = get_engine()
    if engine is None:
        log.info("A2A task store: in-memory (no DB configured)")
        return None

    from a2a.server.tasks import DatabaseTaskStore

    log.info("A2A task store: DatabaseTaskStore on the shared Cloud SQL engine")
    return DatabaseTaskStore(engine=engine)


def build_runner(agent, *, app_name: str):
    """A Runner with the durable session store, the GCS artifact store (bucket → GCS, else in-memory),"""
    from google.adk.artifacts import GcsArtifactService, InMemoryArtifactService
    from google.adk.runners import Runner

    from common.adk.plugins import LearnDrainPlugin

    bucket = os.environ.get("GCS_BUCKET")
    artifacts = GcsArtifactService(bucket_name=bucket) if bucket else InMemoryArtifactService()
    return Runner(
        app_name=app_name,
        agent=agent,
        session_service=build_session_service(),
        artifact_service=artifacts,
        plugins=[LearnDrainPlugin()],
    )
