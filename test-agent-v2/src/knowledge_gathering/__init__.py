"""Knowledge-Gathering Test Agent (knowledge_gathering).

Read-only Atlassian crawler with a GCS markdown memory bank, exposed over A2A.
See docs/IMPLEMENTATION-PLAN.md for the module map. The A2A ASGI app is `knowledge_gathering.server:app`.
"""

__version__ = "0.1.0"

# ADK env bootstrap (E1) — local `adk web`/`adk run` convenience; no-op when env is already set.
import os as _os

from dotenv import load_dotenv as _load_dotenv

_load_dotenv()  # load a local .env for dev, if present
_os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "1")

import contextlib as _cl

with _cl.suppress(Exception):  # best-effort GCP project auto-detect via ADC; offline → skipped
    import google.auth as _gauth

    _, _project = _gauth.default()
    if _project:
        _os.environ.setdefault("GOOGLE_CLOUD_PROJECT", _project)

from knowledge_gathering import agent  # noqa: F401 — expose root_agent for adk web/run
