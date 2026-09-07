"""Test-Evaluation Agent (test_evaluation) — the third Testing-Agent service.

Scores both upstream artifacts, from the shared GCS memory bank, without importing either scored
agent (reads their persisted output as dicts / via common.memory, run-scoped like refine):
  - evaluate_pack — the KGA pack (ADK trajectory + RAGAS retrieval/generation) -> Pack Quality Score.
  - evaluate_plan — the TPD plan + suite (scope/coverage/oracle/fault + brief groundedness) ->
    Test-Plan Score.
The A2A ASGI app is `test_evaluation.server:app`. See docs/RESEARCH-kga-evaluation-adk-ragas.md and
docs/RESEARCH-tpd-evaluation-adk-testsuite.md.
"""

__version__ = "0.1.0"

# ADK env bootstrap (E1) — local `adk web`/`adk run` convenience; no-op when env is already set.
import contextlib as _cl
import os as _os

from dotenv import load_dotenv as _load_dotenv

_load_dotenv()  # load a local .env for dev, if present
_os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "1")

with _cl.suppress(Exception):  # best-effort GCP project auto-detect via ADC; offline → skipped
    import google.auth as _gauth

    _, _project = _gauth.default()
    if _project:
        _os.environ.setdefault("GOOGLE_CLOUD_PROJECT", _project)

from test_evaluation import agent  # noqa: F401 — expose root_agent for adk web/run
