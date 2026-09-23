"""Test Executor Agent (test_executor) — the Pillar-2 execution + self-heal stage of the pipeline.

A deterministic text-dispatch router (no LLM) that runs the persisted scenarios against a selected
environment, records each tested environment + run to the shared Cloud SQL ledger, and triages
failures. Served by the generic `main:app` (AGENT=test_executor) and fronted on the single MCP gateway.
Design: docs/RESEARCH-test-executor-agent.md. Slice 0 = agent + ledger + wiring with a stub runner; the
real Playwright/behave/Schemathesis run (P1) lands behind a flag next.
"""

from __future__ import annotations

__version__ = "0.1.0"

from dotenv import load_dotenv as _load_dotenv

_load_dotenv()  # local GCS_BUCKET / DB creds; no model — the executor runs no LLM in slice 0.

from test_executor import agent  # noqa: F401 — expose root_agent for main.py / adk
