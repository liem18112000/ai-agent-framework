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


def build_runner(agent, *, app_name: str):
    """A Runner with the durable session store, the GCS artifact store (bucket → GCS, else in-memory),"""
    from google.adk.artifacts import GcsArtifactService, InMemoryArtifactService
    from google.adk.runners import Runner

    from common.adk.plugins import LearnDrainPlugin, LessonRecallPlugin

    bucket = os.environ.get("GCS_BUCKET")
    artifacts = GcsArtifactService(bucket_name=bucket) if bucket else InMemoryArtifactService()
    return Runner(
        app_name=app_name,
        agent=agent,
        session_service=build_session_service(),
        artifact_service=artifacts,
        plugins=[LearnDrainPlugin(), LessonRecallPlugin()],
    )
