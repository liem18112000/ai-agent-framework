"""Memory & History Admin Agent (admin_agent) — an operator utility, NOT part of the testing pipeline.

A deterministic text-dispatch router (no LLM) that reads / resets / snapshots the memory bank and the
shared task/session store. Served by the generic `main:app` (AGENT=admin_agent) and surfaced on the
gateway under a marked `[ADMIN — non-pipeline]` tool group.
"""

from __future__ import annotations

__version__ = "0.1.0"

from dotenv import load_dotenv as _load_dotenv

_load_dotenv()  # local GCS_BUCKET / DB creds; no model — admin runs no LLM.

from admin_agent import agent  # noqa: F401 — expose root_agent for main.py / adk
