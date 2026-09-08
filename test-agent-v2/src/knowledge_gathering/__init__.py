"""Knowledge-Gathering Test Agent (knowledge_gathering)."""

__version__ = "0.1.0"

import os as _os

from dotenv import load_dotenv as _load_dotenv

_load_dotenv()
_os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "1")

import contextlib as _cl

with _cl.suppress(Exception):
    import google.auth as _gauth

    _, _project = _gauth.default()
    if _project:
        _os.environ.setdefault("GOOGLE_CLOUD_PROJECT", _project)

from knowledge_gathering import agent  # noqa: F401 — expose root_agent for adk web/run
