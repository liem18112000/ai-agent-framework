"""testing_agent — the opt-in autonomous end-to-end pipeline (E7)."""

import os

from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "1")

from testing_agent.agent import root_agent

__all__ = ["root_agent"]
