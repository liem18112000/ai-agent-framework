"""Knowledge-Gathering Test Agent (knowledge_gathering)."""

__version__ = "0.1.0"

from common.bootstrap import bootstrap_adk

bootstrap_adk()

from knowledge_gathering import agent  # noqa: F401 — expose root_agent for adk web/run
