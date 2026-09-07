"""testing_agent — the opt-in autonomous end-to-end pipeline (E7).

A SequentialAgent composing the KGA gather + headless refine/define/approve + TPD implement. Import
`root_agent` for `adk web`/`to_a2a`. The default gated path (KGA/TPD routers + human confirm-gates)
is unaffected.
"""

# ADK env bootstrap (E1) — before importing agent (adk web/run convenience).
import os

from dotenv import load_dotenv

load_dotenv()  # load a local .env for dev, if present
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "1")

from testing_agent.agent import root_agent

__all__ = ["root_agent"]
