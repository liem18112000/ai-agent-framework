"""Test Executor — route-by-nature engine selection + the real API engine (offline via MockTransport)."""

from __future__ import annotations

import httpx

from test_executor import runners
from test_executor.runner import heal_step, run_suite
from test_executor.runners import ENGINES, ApiEngine, LlmEngine, select_engine
from test_executor.store import InMemoryExecStore


def test_select_engine_routes_by_methodology():
    assert select_engine({"methodology": "api"}) == "api"
    assert select_engine({"methodology": "rest"}) == "api"
    assert select_engine({}) == "api"                       # default methodology is "api"
    assert select_engine({"methodology": "ui"}) == "browser"
    assert select_engine({"methodology": "e2e"}) == "browser"
    assert select_engine({"methodology": "exploratory"}) == "llm"


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
    scenarios.append({"methodology": "ui", "title": "ui nl"})   # browser-NL also needs the LLM → budgeted
    run = await run_suite(store, "CTX", "dev", scenarios=scenarios, base_url="http://svc")
    assert run["summary"]["unbound"] == 4
    assert checked == []            # budget 0 → no engine invoked, so no model call is attempted


class _FakeDriver:
    """Offline BrowserDriver double — records actions, returns a canned page body."""

    def __init__(self, body: str = "", fail_on: str | None = None) -> None:
        self.body, self.fail_on, self.actions = body, fail_on, []

    async def goto(self, url):
        self.actions.append(("goto", url))

    async def act(self, action, selector="", value=""):
        if action == self.fail_on:
            raise RuntimeError("boom")
        self.actions.append((action, selector, value))

    async def text(self):
        return self.body

    async def close(self):
        self.actions.append(("close",))


async def test_browser_engine_runs_plan(monkeypatch):
    driver = _FakeDriver(body="Welcome — you are logged in")
    monkeypatch.setattr(runners, "_browser_driver", driver)
    plan = {"url_path": "/login",
            "steps": [{"action": "fill", "selector": "#u", "value": "x"}, {"action": "click", "selector": "#go"}],
            "expect_text": "logged in"}
    res = await runners.BrowserEngine().run({"methodology": "ui", "browser": plan}, base_url="http://svc")
    assert res.ran and res.passed
    assert ("goto", "http://svc/login") in driver.actions and ("close",) in driver.actions


async def test_browser_engine_expect_text_fail(monkeypatch):
    monkeypatch.setattr(runners, "_browser_driver", _FakeDriver(body="error page"))
    res = await runners.BrowserEngine().run({"browser": {"url_path": "/x", "expect_text": "success"}},
                                            base_url="http://svc")
    assert res.ran and not res.passed and "missing expected" in res.outcomes[-1].message


async def test_browser_engine_unbound_without_plan():
    res = await runners.BrowserEngine().run({"methodology": "ui", "title": "nl ui"}, base_url="http://svc")
    assert res.ran is False and "browser plan" in res.note


async def test_browser_engine_unbound_without_playwright(monkeypatch):
    monkeypatch.setattr(runners, "_browser_driver", None)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None if name == "playwright" else object())
    res = await runners.BrowserEngine().run({"browser": {"url_path": "/x"}}, base_url="http://svc")
    assert res.ran is False and "Playwright" in res.note


async def test_browser_engine_llm_translates_nl(monkeypatch):
    from tests.conftest import fake_model
    canned = ('{"url_path":"/login","steps":[{"action":"fill","selector":"#u","value":"x"},'
              '{"action":"click","selector":"#go"}],"expect_text":"Welcome"}')
    monkeypatch.setattr("common.adk.model.model_configured", lambda: True)
    monkeypatch.setattr("common.adk.model.agent_model", lambda **k: fake_model(canned))
    driver = _FakeDriver(body="Welcome home")
    monkeypatch.setattr(runners, "_browser_driver", driver)
    res = await runners.BrowserEngine().run({"methodology": "ui", "title": "user logs in"}, base_url="http://svc")
    assert res.ran and res.passed
    assert ("goto", "http://svc/login") in driver.actions       # LLM-translated plan actually executed


async def test_run_suite_chunks_and_resumes(monkeypatch):
    monkeypatch.setenv("EXEC_RUNNER", "auto")
    monkeypatch.setenv("EXEC_CHUNK", "1")                       # one scenario per poll
    monkeypatch.setattr(runners, "_transport", httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    store = InMemoryExecStore()
    scs = [{"title": f"s{i}", "methodology": "api", "request": {"path": f"/{i}", "expect_status": 200}}
           for i in range(3)]
    r1 = await run_suite(store, "CTX", "dev", scenarios=scs, base_url="http://svc")
    assert r1["status"] == "in_progress" and r1["summary"]["executed"] == 1
    r2 = await run_suite(store, "CTX", scenarios=scs, base_url="http://svc")     # poll → resume
    assert r2["status"] == "in_progress" and r2["summary"]["executed"] == 2 and r2["id"] == r1["id"]
    r3 = await run_suite(store, "CTX", scenarios=scs, base_url="http://svc")     # poll → done
    assert r3["status"] == "done" and r3["summary"]["passed"] == 3 and r3["summary"]["executed"] == 3
    r4 = await run_suite(store, "CTX", "dev", scenarios=scs, base_url="http://svc")  # after done → fresh run
    assert r4["id"] != r3["id"] and r4["status"] == "in_progress"


async def _seed_failed_run(message: str) -> InMemoryExecStore:
    store = InMemoryExecStore()
    eid = await store.upsert_env("CTX", "dev")
    rid = await store.start_run("CTX", eid)
    await store.finish_run(rid, status="done", summary={"failed": 1},
                           signals={"failures": [{"scenario": "s1", "message": message}]}, triage=[])
    return store


async def test_heal_step_proposes_and_verifies(monkeypatch):
    from tests.conftest import fake_model
    monkeypatch.setattr("common.adk.model.model_configured", lambda: True)
    monkeypatch.setattr("common.adk.model.agent_model",
                        lambda **k: fake_model('{"method":"GET","path":"/fixed","expect_status":200}'))
    monkeypatch.setattr(runners, "_transport", httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    store = await _seed_failed_run("500 server error")
    result = await heal_step(store, "CTX", "s1", scenarios=[{"title": "s1", "methodology": "api"}],
                             base_url="http://svc")
    assert result["healed"] is True and result["engine"] == "api" and result["patch"]["path"] == "/fixed"


async def test_heal_step_no_failure_to_heal():
    store = InMemoryExecStore()
    rid = await store.start_run("CTX", None)
    await store.finish_run(rid, status="done", summary={}, signals={"failures": []}, triage=[])
    result = await heal_step(store, "CTX", "s1", scenarios=[{"title": "s1"}], base_url="http://svc")
    assert result["healed"] is False and "no failed step" in result["note"]


async def test_heal_step_needs_provider(monkeypatch):
    monkeypatch.setattr("common.adk.model.model_configured", lambda: False)
    store = await _seed_failed_run("selector #btn not found")
    result = await heal_step(store, "CTX", "s1", scenarios=[{"title": "s1"}], base_url="http://svc")
    assert result["healed"] is False and "provider" in result["note"]
