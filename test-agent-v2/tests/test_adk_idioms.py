"""E1 (CLI-discoverable root_agent + env bootstrap) and E4 (cross-cutting Plugin fires)."""

from __future__ import annotations

import os
import types as _t

from common.memory import MemoryBank
from tests.conftest import FakeBucket


def test_root_agents_are_discoverable():
    from knowledge_gathering.agent import root_agent as kga
    from test_evaluation.agent import root_agent as ev
    from test_plan_definition.agent import root_agent as tpd
    from testing_agent.agent import root_agent as ta

    assert kga.name == "knowledge_gathering"
    assert tpd.name == "test_plan_definition"
    assert ev.name == "test_evaluation"
    assert ta.name == "testing_agent"
    assert [a.name for a in ta.sub_agents] == ["gather", "refine", "define", "approve", "implement"]


def test_env_bootstrap_sets_vertexai_flag():
    import knowledge_gathering  # noqa: F401 — importing runs the __init__ bootstrap
    assert os.environ.get("GOOGLE_GENAI_USE_VERTEXAI")


async def test_learn_drain_plugin_before_run_fires(monkeypatch):
    import common.adk.plugins as pl

    bank = MemoryBank(FakeBucket())
    called = {}
    monkeypatch.setattr(pl, "build_bank", lambda: bank)
    monkeypatch.setattr(pl.learn, "capture_enabled", lambda prefix: True)
    monkeypatch.setattr(pl.learn, "drain", lambda b, now=None: called.setdefault("drain", (b, now)))

    ic = _t.SimpleNamespace(app_name="knowledge_gathering", agent=None)
    result = await pl.LearnDrainPlugin().before_run_callback(invocation_context=ic)

    assert result is None
    assert called["drain"][0] is bank
