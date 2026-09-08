"""Test-Evaluation Agent (test_evaluation) — the third Testing-Agent service."""

__version__ = "0.1.0"

import contextlib as _cl
import os as _os

from dotenv import load_dotenv as _load_dotenv

_load_dotenv()
_os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "1")

with _cl.suppress(Exception):
    import google.auth as _gauth

    _, _project = _gauth.default()
    if _project:
        _os.environ.setdefault("GOOGLE_CLOUD_PROJECT", _project)

from test_evaluation import agent  # noqa: F401 — expose root_agent for adk web/run
