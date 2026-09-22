"""G2 opt-in parallel planners — `_plan` fans the 3 planners out concurrently (isolated sessions) when
`KGA_PLANNER_PARALLEL` is set, and assembles terms/leads/cloud_plan the same as the serial default."""

from __future__ import annotations

from types import SimpleNamespace

from knowledge_gathering.gather.agent import build_gather_agent
from knowledge_gathering.gather.explore.planners.ask_llm import OUTPUT_KEY as LEADS_KEY
from knowledge_gathering.gather.explore.planners.cloud_explore import OUTPUT_KEY as CLOUD_KEY
from knowledge_gathering.gather.explore.planners.hypothesize import OUTPUT_KEY as HYP_KEY

_CANNED = {
    HYP_KEY: {"key_phrases": ["dunning"], "entities": ["invoice"], "subsystems": ["billing"]},
    LEADS_KEY: {"phrases": ["retry logic"]},
    CLOUD_KEY: {"priority_services": ["luz-billing"], "clusters": []},
}


def _probe():
    return SimpleNamespace(title="Dunning export fails", description="body", labels=["billing"], terms="seed terms")


def _ctx():
    return SimpleNamespace(session=SimpleNamespace(state={}, id="t1"))


async def test_parallel_dispatches_all_and_assembles(monkeypatch):
    monkeypatch.setenv("KGA_PLANNER_PARALLEL", "1")
    agent = build_gather_agent()

    iso_calls, serial_calls = [], []

    async def _fake_iso(plan_input, ag, output_key):
        iso_calls.append(output_key)
        return _CANNED[output_key]

    async def _fake_serial(ctx, ag, output_key):  # must NOT be used in parallel mode
        serial_calls.append(output_key)
        return _CANNED[output_key]

    monkeypatch.setattr(agent, "_run_planner_isolated", _fake_iso)
    monkeypatch.setattr(agent, "_run_planner", _fake_serial)

    terms, leads, planner_md, cloud_plan = await agent._plan(_ctx(), _probe(), cloud_on=True)

    assert sorted(iso_calls) == sorted([HYP_KEY, LEADS_KEY, CLOUD_KEY])  # all enabled fired, isolated
    assert serial_calls == []                                           # serial path not taken
    assert terms == "dunning invoice billing"
    assert leads == ["retry logic"]
    assert cloud_plan.priority_services == ["luz-billing"]
    assert any("Hypothesized focus" in m for m in planner_md)


async def test_serial_default_skips_cloud_when_off(monkeypatch):
    monkeypatch.delenv("KGA_PLANNER_PARALLEL", raising=False)  # default → serial
    agent = build_gather_agent()

    used = []

    async def _fake_iso(*a, **k):
        used.append("iso")

    async def _fake_serial(ctx, ag, output_key):
        used.append(output_key)
        return _CANNED[output_key]

    monkeypatch.setattr(agent, "_run_planner_isolated", _fake_iso)
    monkeypatch.setattr(agent, "_run_planner", _fake_serial)

    terms, leads, _md, cloud_plan = await agent._plan(_ctx(), _probe(), cloud_on=False)

    assert "iso" not in used                       # serial path
    assert CLOUD_KEY not in used and cloud_plan is None  # cloud planner gated off by cloud_on=False
    assert terms == "dunning invoice billing" and leads == ["retry logic"]
