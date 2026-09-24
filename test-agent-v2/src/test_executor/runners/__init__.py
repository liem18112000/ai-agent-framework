"""Execution engines + the route-by-nature selector.

The Executor does not hard-pick one runner: it routes each scenario to the engine that fits its
*nature*, using the scenario's own declared `methodology` (`common.testplan.models.TestScenario`,
default "api") as the routing key — not a fragile text heuristic. Design §3 lists all three engines:

  methodology  →  engine
  api/rest/http/service  →  ApiEngine       (deterministic httpx conformance)
  ui/e2e/browser/web     →  BrowserEngine    (Playwright; LLM-translates a NL scenario to a browser plan)
  everything else        →  LlmEngine        (LLM-translates a NL scenario to an HTTP request)

Each engine returns an `EngineResult`. `ran=False` means "unbound" — the engine can't execute this
scenario (no executable binding / no provider); that is recorded honestly, never faked as a pass.

Package layout: `base` (result types, Protocol, egress allow-list) · `translate` (plan models + the
shared request helpers + heal) · `engines/` (the three *Engine classes) · `select` (route + registry).
"""

from __future__ import annotations

from test_executor.runners.base import (
    _MAX_RESPONSE_BYTES,
    EngineResult,
    RunnerEngine,
    StepOutcome,
    _same_site,
    log,
)
from test_executor.runners.engines import (
    ApiEngine,
    BrowserDriver,
    BrowserEngine,
    LlmEngine,
    PlaywrightDriver,
)
from test_executor.runners.select import _API, _UI, ENGINES, select_engine

# The suite orchestrator (run one chunk over the engines + triage + heal) — imported last: it depends on
# select + translate, which are loaded above.
from test_executor.runners.suite import (
    classify_failure,
    heal_step,
    load_scenarios,
    run_suite,
    triage,
)
from test_executor.runners.translate import (
    BrowserPlan,
    BrowserStep,
    RequestPlan,
    _llm_translate,
    _request_from_plan,
    _scenario_task,
    _send_kwargs,
    _subst_path,
    heal,
)

#: Test seams — patched as `runners._transport` / `runners._browser_driver`; the engines read them at
#: call time via `from test_executor import runners`, so a monkeypatch on THIS module reaches them.
#: Defined after the engine imports (engines don't read them at import), so no E402 / no cycle.
_transport = None          #: an httpx transport override (MockTransport/ASGITransport) → ApiEngine offline
_browser_driver = None     #: a BrowserDriver override → BrowserEngine offline (no real browser binary)

__all__ = [
    "ENGINES",
    "_API",
    "_MAX_RESPONSE_BYTES",
    "_UI",
    "ApiEngine",
    "BrowserDriver",
    "BrowserEngine",
    "BrowserPlan",
    "BrowserStep",
    "EngineResult",
    "LlmEngine",
    "PlaywrightDriver",
    "RequestPlan",
    "RunnerEngine",
    "StepOutcome",
    "_browser_driver",
    "_llm_translate",
    "_request_from_plan",
    "_same_site",
    "_scenario_task",
    "_send_kwargs",
    "_subst_path",
    "_transport",
    "classify_failure",
    "heal",
    "heal_step",
    "load_scenarios",
    "log",
    "run_suite",
    "select_engine",
    "triage",
]
