"""Test-Evaluation Agent (test_evaluation) — the third Testing-Agent service."""

__version__ = "0.1.0"

from common.bootstrap import bootstrap_adk

bootstrap_adk()

from test_evaluation import agent  # noqa: F401 — expose root_agent for adk web/run
