"""Test Executor — router dispatch through the real ADK Runner, offline (in-memory ledger)."""

from __future__ import annotations

import pytest

from test_executor.agent import build_root_agent
from test_executor.store import InMemoryExecStore
from tests.conftest import drive_adk


@pytest.fixture
def mem(monkeypatch):
    """Bind the agent to one in-memory ledger shared across the test's drive_adk calls."""
    store = InMemoryExecStore()
    monkeypatch.setattr("test_executor.agent.build_store", lambda: store)
    return store


async def test_unknown_verb_lists_verbs(mem):
    assert "Executor verbs" in await drive_adk(build_root_agent, "wat")


async def test_run_needs_ctx(mem):
    assert "context id" in (await drive_adk(build_root_agent, "run")).lower()


async def test_run_then_report(mem):
    out = await drive_adk(build_root_agent, "run CTX dev")
    assert "stub" in out.lower()
    report = await drive_adk(build_root_agent, "report CTX")
    assert "status: done" in report


async def test_environments_listed(mem):
    await drive_adk(build_root_agent, "run CTX staging")
    out = await drive_adk(build_root_agent, "environments CTX")
    assert "staging" in out


async def test_triage_without_run(mem):
    assert "call run first" in (await drive_adk(build_root_agent, "triage CTX")).lower()
