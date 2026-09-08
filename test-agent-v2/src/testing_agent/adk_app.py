"""Autonomous Testing Agent — ADK A2A app (E7). `uvicorn testing_agent.adk_app:app`."""

from __future__ import annotations

from common.adk.serve import serve
from testing_agent.agent import root_agent

_REQUIRED_ENV = ("ATLASSIAN_BASE_URL", "ATLASSIAN_EMAIL", "ATLASSIAN_API_TOKEN", "GCS_BUCKET")

app = serve(root_agent, _REQUIRED_ENV)
