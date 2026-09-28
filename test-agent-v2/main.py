"""Single A2A entrypoint — one agent per container, selected by $AGENT. Run: `uvicorn main:app`.

Resolves $AGENT to its `root_agent` and serves it through the A2A seam (`common.adk.serve`), which
owns all server-side A2A/ADK wiring (to_a2a, Runner, durable task store, health probes, bearer auth).
"""

from __future__ import annotations

import importlib
import os

from common.adk.serve import build_agent_app

_AGENT = os.environ.get("AGENT", "knowledge_gathering")
_ATLASSIAN = ("ATLASSIAN_BASE_URL", "ATLASSIAN_EMAIL", "ATLASSIAN_API_TOKEN", "GCS_BUCKET")
_REQUIRED_ENV = {"knowledge_gathering": _ATLASSIAN, "testing_agent": _ATLASSIAN,
                 "admin_agent": ("GCS_BUCKET",)}


def build_app(module: str = _AGENT):
    root = importlib.import_module(f"{module}.agent").root_agent
    return build_agent_app(root, required_env=_REQUIRED_ENV.get(module, ("GCS_BUCKET",)))


app = build_app()
