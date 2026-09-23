"""Test Executor — route-by-nature engine selection + the real API engine (offline via MockTransport)."""

from __future__ import annotations

import httpx

from test_executor import runners
from test_executor.runner import run_suite
from test_executor.runners import ENGINES, ApiEngine, LlmEngine, select_engine
from test_executor.store import InMemoryExecStore


def test_select_engine_routes_by_methodology():
    assert select_engine({"methodology": "api"}) == "api"
    assert select_engine({"methodology": "rest"}) == "api"
    assert select_engine({}) == "api"                       # default methodology is "api"
    assert select_engine({"methodology": "ui"}) == "browser"
    assert select_engine({"methodology": "e2e"}) == "browser"
    assert select_engine({"methodology": "exploratory"}) == "llm"


async def test_browser_engine_reports_unbound():
    # BrowserEngine is still a stub behind the seam (LlmEngine is now real — see its own tests).
    res = await ENGINES["browser"].run({"methodology": "ui"}, base_url="http://x")
    assert res.ran is False and "not built" in res.note


async def test_api_engine_conformance_pass(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"ok": True})
    monkeypatch.setattr(runners, "_transport", httpx.MockTransport(handler))
    res = await ApiEngine().run({"request": {"path": "/health", "expect_status": 200}}, base_url="http://svc")
    assert res.ran and res.passed


async def test_api_engine_status_mismatch_fails(monkeypatch):
    monkeypatch.setattr(runners, "_transport", httpx.MockTransport(lambda r: httpx.Response(500)))
    res = await ApiEngine().run({"request": {"path": "/charge", "expect_status": 200}}, base_url="http://svc")
    assert res.ran and not res.passed and "status 500" in res.outcomes[0].message


async def test_api_engine_no_binding_is_unbound():
    res = await ApiEngine().run({"methodology": "api", "title": "NL-only scenario"}, base_url="http://svc")
    assert res.ran is False and "no executable request" in res.note


async def test_run_suite_auto_aggregates(monkeypatch):
    monkeypatch.setenv("EXEC_RUNNER", "auto")
    monkeypatch.setattr(runners, "_transport", httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    store = InMemoryExecStore()
    scenarios = [
        {"title": "happy", "methodology": "api", "request": {"path": "/ok", "expect_status": 200}},
        {"title": "ui flow", "methodology": "ui"},          # → browser stub → unbound
        {"title": "nl", "methodology": "api"},              # → api, no binding → unbound
    ]
    run = await run_suite(store, "CTX", "dev", scenarios=scenarios, base_url="http://svc")
    assert run["summary"]["passed"] == 1
    assert run["summary"]["unbound"] == 2
    assert run["summary"]["executed"] == 1


async def test_run_suite_stub_default(monkeypatch):
    monkeypatch.delenv("EXEC_RUNNER", raising=False)
    store = InMemoryExecStore()
    run = await run_suite(store, "CTX", "dev", scenarios=[{"methodology": "api"}])
    assert run["signals"].get("stub") is True


async def test_load_scenarios_reads_bank(monkeypatch):
    from common.memory import MemoryBank
    from common.store.memory import InMemoryObjectStore
    from common.testplan import memory as tp_store
    from common.testplan.models import TestScenario
    from test_executor import runner

    bank = MemoryBank(InMemoryObjectStore())
    tp_store.write_scenarios(bank, "CTX", [
        TestScenario(id="s1", plan_id="p", title="charge happy", methodology="api"),
        TestScenario(id="s2", plan_id="p", title="login UI", methodology="ui"),
    ])
    monkeypatch.setattr("common.memory.factory.build_bank", lambda: bank)
    scenarios = await runner.load_scenarios("CTX")
    assert len(scenarios) == 2
    assert {s["methodology"] for s in scenarios} == {"api", "ui"}
    # unknown context → empty, never a crash
    assert await runner.load_scenarios("NOPE") == []


async def test_api_engine_expect_contains_fail(monkeypatch):
    monkeypatch.setattr(runners, "_transport", httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    res = await ApiEngine().run({"request": {"path": "/x", "expect_status": 200, "expect_contains": "DONE"}},
                                base_url="http://svc")
    assert res.ran and not res.passed and "missing expected" in res.outcomes[-1].message


async def test_llm_engine_unbound_without_provider():
    # offline default: no model provider configured → unbound, no call, never a fake pass
    res = await ENGINES["llm"].run({"methodology": "exploratory", "title": "x"}, base_url="http://svc")
    assert res.ran is False and "provider" in res.note


async def test_llm_engine_translates_and_executes(monkeypatch):
    from tests.conftest import fake_model
    canned = ('{"method":"POST","path":"/charge","body":{"amount":1},'
              '"expect_status":200,"expect_contains":"CHARGED"}')
    monkeypatch.setattr("common.adk.model.model_configured", lambda: True)
    monkeypatch.setattr("common.adk.model.agent_model", lambda **k: fake_model(canned))
    monkeypatch.setattr(runners, "_transport",
                        httpx.MockTransport(lambda r: httpx.Response(200, json={"status": "CHARGED"})))
    res = await LlmEngine().run({"methodology": "exploratory", "title": "charge succeeds"}, base_url="http://svc")
    assert res.ran and res.passed


async def test_run_suite_llm_budget_makes_no_call(monkeypatch):
    monkeypatch.setenv("EXEC_RUNNER", "auto")
    monkeypatch.setenv("EXEC_LLM_MAX", "0")
    checked = []
    monkeypatch.setattr("common.adk.model.model_configured", lambda: checked.append(1) or True)
    store = InMemoryExecStore()
    scenarios = [{"methodology": "exploratory", "title": f"s{i}"} for i in range(3)]
    run = await run_suite(store, "CTX", "dev", scenarios=scenarios, base_url="http://svc")
    assert run["summary"]["unbound"] == 3
    assert checked == []            # budget 0 → the engine is never invoked, so no model call is attempted
