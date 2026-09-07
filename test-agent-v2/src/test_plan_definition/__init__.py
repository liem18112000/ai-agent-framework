"""Test-Plan Definition agent (test_plan_definition).

Step 3+4 of the Testing Agent: turn an approved insight pack (the "Collect insight"
hand-off from `knowledge_gathering`) into a confirmed Test Plan, then generate its test
data / scenarios / steps. Mirrors the `knowledge_gathering` skeleton — an A2A agent over
the shared GCS memory bank, driven by local Claude — but runs reconfirm -> generate
(define multi-turn, then implement one-shot) where gather ran generate -> reconfirm.

See docs/PROPOSAL-TEST-PLAN-DEFINITION.md for the module map. The A2A ASGI app is
`test_plan_definition.server:app`.
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

from test_plan_definition import agent  # noqa: F401 — expose root_agent for adk web/run
