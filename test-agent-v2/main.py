"""Canonical ADK API server — the standard container entrypoint (`get_fast_api_app`).

This is the vanilla way ADK agents are served/deployed: ADK's own FastAPI app, auto-discovering every
agent package under `src/` (knowledge_gathering, test_plan_definition, test_evaluation, testing_agent)
and exposing the ADK REST/SSE API (`/run`, `/run_sse`, `/list-apps`, session + artifact endpoints),
plus A2A per agent (`a2a=True`) and, optionally, the `adk web` dev UI.

Run locally:      uvicorn main:app --host 0.0.0.0 --port 8080
Deploy (managed): adk deploy cloud_run --project <p> --region <r> --with_ui src
Deploy (manual):  gcloud run deploy <svc> --source . --region <r> --project <p>

The hand-rolled Terraform in `../deployments/test-agent-v2` is the *A2A-only* alternative that keeps
the existing MCP bridge (bridge -> A2A `to_a2a`); this file is the ADK-native REST+A2A server. See
docs/DEPLOY.md for when to use which.
"""

from __future__ import annotations

import os

from google.adk.cli.fast_api import get_fast_api_app

_AGENTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")


def _bool(name: str) -> bool:
    return os.environ.get(name, "").lower() in ("1", "true", "yes", "on")


_kwargs: dict = {
    "agents_dir": _AGENTS_DIR,
    "a2a": True,                                    # also expose A2A per agent
    "web": _bool("ADK_WEB"),                        # dev UI (off by default — not for prod)
    "trace_to_cloud": _bool("ADK_TRACE_TO_CLOUD"),  # Cloud Trace export
}
# Durable stores when configured (else ADK defaults to in-memory / local):
#   SESSION_SERVICE_URI  e.g. postgresql+asyncpg://…  (DatabaseSessionService)
#   ARTIFACT_SERVICE_URI e.g. gs://<bucket>           (GcsArtifactService)
for env, kw in (("SESSION_SERVICE_URI", "session_service_uri"),
                ("ARTIFACT_SERVICE_URI", "artifact_service_uri"),
                ("MEMORY_SERVICE_URI", "memory_service_uri")):
    if os.environ.get(env):
        _kwargs[kw] = os.environ[env]
if os.environ.get("ADK_ALLOW_ORIGINS"):
    _kwargs["allow_origins"] = [o for o in os.environ["ADK_ALLOW_ORIGINS"].split(",") if o]

app = get_fast_api_app(**_kwargs)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
