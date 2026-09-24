"""Test Executor — route-by-nature engine selection + the real API engine (offline via MockTransport)."""

from __future__ import annotations

import asyncio

import httpx

from test_executor import runners
from test_executor.runners import ENGINES, ApiEngine, LlmEngine, heal_step, run_suite, select_engine
from test_executor.store import InMemoryExecStore


def test_select_engine_routes_by_methodology():
    assert select_engine({"methodology": "api", "request": {"path": "/x"}}) == "api"   # bound → deterministic
    assert select_engine({"methodology": "rest", "request": {"path": "/x"}}) == "api"
    assert select_engine({"methodology": "api"}) == "llm"   # NL api (no request) → translate via the LLM
    assert select_engine({}) == "llm"                       # default api, no binding → LLM
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
    from test_executor.runners import suite as runner

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


async def test_browser_engine_blocks_offsite_goto_step(monkeypatch):
    """EXEC-01: a nav step to a foreign host (scenario-controlled) is refused, never reaches the driver."""
    driver = _FakeDriver()
    monkeypatch.setattr(runners, "_browser_driver", driver)
    plan = {"url_path": "/", "steps": [{"action": "goto", "value": "http://169.254.169.254/latest"}]}
    res = await runners.BrowserEngine().run({"methodology": "ui", "browser": plan}, base_url="http://svc")
    assert ("goto", "http://169.254.169.254/latest") not in driver.actions   # never navigated off-site
    assert any("blocked off-site" in o.message for o in res.outcomes)


async def test_browser_engine_allows_samesite_goto_step(monkeypatch):
    """EXEC-01: a same-host (relative) nav step resolves against base_url and is allowed."""
    driver = _FakeDriver()
    monkeypatch.setattr(runners, "_browser_driver", driver)
    plan = {"url_path": "/", "steps": [{"action": "goto", "value": "/dashboard"}]}
    await runners.BrowserEngine().run({"methodology": "ui", "browser": plan}, base_url="http://svc")
    assert ("goto", "http://svc/dashboard") in driver.actions


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


# --- per-scenario results: the rows a test-completion report is built from -------------------------
async def test_run_records_a_result_row_for_every_scenario_including_passes(monkeypatch):
    """A coverage matrix is `requirement -> covering scenario -> result -> evidence`, so the run must
    keep a row per scenario INCLUDING the passes — counts alone cannot produce one."""
    monkeypatch.setenv("EXEC_RUNNER", "auto")
    monkeypatch.setattr(runners, "_transport", httpx.MockTransport(
        lambda r: httpx.Response(200 if r.url.path == "/ok" else 500, json={})))
    store = InMemoryExecStore()
    scs = [{"id": "s1", "title": "green one", "kind": "happy", "methodology": "api",
            "source_refs": ["jira:AC-1"], "request": {"method": "GET", "path": "/ok", "expect_status": 200}},
           {"id": "s2", "title": "red one", "kind": "negative", "methodology": "api",
            "source_refs": ["jira:AC-2"], "request": {"method": "GET", "path": "/bad", "expect_status": 200}}]
    run = await run_suite(store, "CTX", "", scenarios=scs, base_url="https://svc")

    rows = {r["id"]: r for r in run["signals"]["results"]}
    assert set(rows) == {"s1", "s2"}                        # the PASS is recorded, not just the failure
    assert rows["s1"]["status"] == "passed" and rows["s1"]["messages"] == []
    assert rows["s1"]["source_refs"] == ["jira:AC-1"]       # traceability back to the requirement
    assert rows["s1"]["method"] == "GET" and rows["s1"]["path"] == "/ok"   # what was exercised
    assert rows["s2"]["status"] == "failed" and rows["s2"]["messages"]
    assert all(r["engine"] == "api" and r["duration_ms"] >= 0 for r in rows.values())


async def test_results_survive_the_chunked_resume(monkeypatch):
    """Rows accumulate across polls — a long run's report must cover every chunk, not just the last."""
    monkeypatch.setenv("EXEC_RUNNER", "auto")
    monkeypatch.setenv("EXEC_CHUNK", "1")
    monkeypatch.setattr(runners, "_transport", httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    store = InMemoryExecStore()
    scs = [{"id": f"s{i}", "title": f"t{i}", "methodology": "api",
            "request": {"method": "GET", "path": f"/p{i}", "expect_status": 200}} for i in range(3)]
    for _ in range(3):
        run = await run_suite(store, "CTX", "", scenarios=scs, base_url="https://svc")
    assert run["status"] == "done"
    assert [r["id"] for r in run["signals"]["results"]] == ["s0", "s1", "s2"]


def test_render_run_shows_rows_and_prompts_for_the_report():
    from test_executor.ops import render_run
    run = {"id": "r1", "status": "done", "environment_id": "CTX:dev",
           "summary": {"passed": 1, "failed": 0},
           "signals": {"total": 1, "results": [
               {"id": "s1", "title": "green one", "status": "passed", "engine": "api", "kind": "happy",
                "source_refs": ["jira:AC-1"], "method": "GET", "path": "/ok", "messages": [],
                "duration_ms": 12}]}}
    out = render_run(run)
    assert "[passed] green one" in out and "covers=jira:AC-1" in out and "GET /ok" in out
    assert "results (1 scenarios" in out
    assert "TEST COMPLETION REPORT" in out            # the completion cue the client acts on
    assert "'results':" not in out                    # not dumped as a raw k=v blob

    # an in-progress run must NOT prompt for the report yet
    assert "TEST COMPLETION REPORT" not in render_run({**run, "status": "in_progress"})



def test_render_run_surfaces_scope_and_period_for_the_report():
    """Report template §1 (Scope: tested item + version + environment) and §3 (test period) must be
    readable off the run — they were stored or knowable but never surfaced."""
    from test_executor.ops import render_run
    out = render_run({
        "id": "r1", "status": "done", "environment_id": "CTX:luz-dev",
        "started_at": "2026-09-24T10:00:00Z", "finished_at": "2026-09-24T10:02:30Z",
        "summary": {"passed": 2, "failed": 0},
        "signals": {"total": 2, "results": [],
                    "target": {"env": "luz-dev", "base_url": "http://svc:8080/luz_docs",
                               "item": "luz_docs.war", "item_version": "0.01.18.00"}}})
    assert "item=luz_docs.war" in out and "item_version=0.01.18.00" in out   # §1 test item + version
    assert "base_url=http://svc:8080/luz_docs" in out                         # §1 environment
    assert "2026-09-24T10:00:00Z → 2026-09-24T10:02:30Z" in out               # §3 test period


async def test_run_records_the_target_scope(monkeypatch):
    monkeypatch.setenv("EXEC_RUNNER", "auto")
    monkeypatch.setattr(runners, "_transport", httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    run = await run_suite(InMemoryExecStore(), "CTX", "dev", base_url="https://svc",
                          scenarios=[{"id": "s", "title": "t", "methodology": "api",
                                      "request": {"method": "GET", "path": "/x", "expect_status": 200}}])
    assert run["signals"]["target"] == {"env": "dev", "base_url": "https://svc"}


async def test_target_labels_the_spec_version_not_the_build(monkeypatch):
    """Found on a LIVE run: the OpenAPI info.version is the CONTRACT's version (SmallRye defaults it to
    '1.0') while the service reported 0.01.18.00-SNAPSHOT. Reporting it as the tested BUILD version would
    put a wrong version in the report's Scope section, so it is labelled spec_version."""
    monkeypatch.setenv("EXEC_RUNNER", "auto")
    monkeypatch.setenv("EXEC_ENVIRONMENTS", '{"e":{"base_url":"https://svc","spec_url":"/openapi"}}')
    spec = {"openapi": "3.0.3", "info": {"title": "luz_docs.war", "version": "1.0"}, "paths": {}}

    async def fake_fetch(spec_url, *, base_url, headers=None):
        return spec
    monkeypatch.setattr("test_executor.oracle.fetch_spec", fake_fetch)
    monkeypatch.setattr("test_executor.runners.suite._persist_spec",
                        lambda *a, **k: asyncio.sleep(0))
    monkeypatch.setattr(runners, "_transport", httpx.MockTransport(lambda r: httpx.Response(200, json={})))

    run = await run_suite(InMemoryExecStore(), "CTX", "e", scenarios=[])
    t = run["signals"]["target"]
    assert t["item"] == "luz_docs.war" and t["spec_version"] == "1.0"
    assert "item_version" not in t          # never claim the spec version is the build version


async def test_fetch_version_reads_the_build_version(monkeypatch):
    """Report §1 wants the DEPLOYED build version. Field name varies per service, and an empty value
    must yield "" so the caller omits it rather than reporting a blank version."""
    from test_executor.runners.suite import _fetch_version
    real = httpx.AsyncClient

    def mock(payload):
        monkeypatch.setattr(httpx, "AsyncClient",
                            lambda **kw: real(transport=httpx.MockTransport(
                                lambda r: httpx.Response(200, json=payload))))

    mock({"luz_docs": "0.01.18.00-SNAPSHOT"})          # field auto-detected (first non-empty string)
    assert await _fetch_version("/api/version", base_url="https://svc") == "0.01.18.00-SNAPSHOT"
    mock({"a": "", "b": "2.1.0"})                       # skips the empty one
    assert await _fetch_version("/api/version", base_url="https://svc") == "2.1.0"
    mock({"x": "1.0", "build": "9.9"})                  # explicit field wins
    assert await _fetch_version("/api/version", base_url="https://svc", field="build") == "9.9"
    mock({"luz_docsimport": ""})                        # real case: the import service reports empty
    assert await _fetch_version("/api/version", base_url="https://svc") == ""


async def test_fetch_version_refuses_offsite_and_never_raises(monkeypatch):
    from test_executor.runners.suite import _fetch_version
    assert await _fetch_version("https://evil.example/v", base_url="https://svc") == ""   # egress gate
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(
                            lambda r: httpx.Response(500, text="boom"))))
    assert await _fetch_version("/api/version", base_url="https://svc") == ""              # 500 → omit


def test_render_run_shows_the_ac_coverage_matrix_with_gaps():
    from test_executor.ops import render_run
    out = render_run({
        "id": "r", "status": "done", "summary": {"passed": 1},
        "signals": {"total": 1, "results": [], "ac_coverage": {
            "total": 3, "covered": 1, "gaps": 2,
            "rows": [{"id": "s#AC-1", "text": "transfer accepted", "status": "passed", "scenarios": ["a"]},
                     {"id": "s#AC-2", "text": "folders recreated", "status": "gap", "scenarios": []},
                     {"id": "s#AC-3", "text": "metadata paired", "status": "gap", "scenarios": []}]}}})
    assert "AC coverage: 1/3 covered, 2 GAP(s)" in out
    assert "[PASS] s#AC-1" in out and "[GAP ] s#AC-2" in out
    assert "'rows':" not in out          # the matrix is a table, never a raw k=v blob
