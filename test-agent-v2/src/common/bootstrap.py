"""Process bootstrap every ADK agent package runs before importing its agent.

Loads `.env`, points google-genai at Vertex, and fills `GOOGLE_CLOUD_PROJECT` from ADC so a local run
matches the deployed one. This was copy-pasted verbatim into three package `__init__.py` files; one
copy drifting is a per-agent behaviour difference nobody would look for.

Imports NOTHING that logs: `common.monitoring` configures its toggle from the environment on the
first `get_logger`, so a module-level logger imported ahead of `load_dotenv()` would freeze the
`*_LOG` toggles at the pre-`.env` values. Keep this module's imports to the stdlib + dotenv.
"""

from __future__ import annotations

import contextlib
import os

from dotenv import load_dotenv


def bootstrap_adk() -> None:
    """Load `.env`, select Vertex for google-genai, and default the project from ADC."""
    load_dotenv()
    os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "1")
    with contextlib.suppress(Exception):  # no ADC locally is normal — the explicit env still wins
        import google.auth

        _, project = google.auth.default()
        if project:
            os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project)
