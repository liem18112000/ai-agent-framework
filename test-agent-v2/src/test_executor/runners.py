"""Execution engines + the route-by-nature selector.

The Executor does not hard-pick one runner: it routes each scenario to the engine that fits its
*nature*, using the scenario's own declared `methodology` (`common.testplan.models.TestScenario`,
default "api") as the routing key — not a fragile text heuristic. Design §3 lists all three engines:

  methodology  →  engine
  api/rest/http/service  →  ApiEngine       (deterministic httpx conformance — BUILT, offline-testable)
  ui/e2e/browser/web     →  BrowserEngine    (Playwright — stub; drops in without a browser dep here)
  everything else        →  LlmEngine        (translate NL steps → actions — stub; needs a provider)

Each engine returns an `EngineResult`. `ran=False` means "unbound" — the engine can't (yet) execute this
scenario (not built, or no executable binding); that is recorded honestly, never faked as a pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from common.monitoring import get_logger

log = get_logger("exec.runners")

#: Test seam — an httpx transport override (MockTransport/ASGITransport) so ApiEngine runs offline.
_transport = None


@dataclass
class StepOutcome:
    ok: bool
    message: str = ""      # failure detail (feeds triage) when not ok
    flaky: bool = False


@dataclass
class EngineResult:
    engine: str
    ran: bool                                        # False = unbound (not built / no executable binding)
    outcomes: list[StepOutcome] = field(default_factory=list)
    note: str = ""

    @property
    def passed(self) -> bool:
        return self.ran and all(o.ok for o in self.outcomes)


@runtime_checkable
class RunnerEngine(Protocol):
    name: str

    async def run(self, scenario: dict, *, base_url: str) -> EngineResult: ...


class ApiEngine:
    """Deterministic API execution: run the scenario's structured request against `base_url` and check
    conformance (status class + JSON validity). A scenario carries an executable binding under
    `request` = {method?, path, json?, expect_status?} (a future TPD or a translator attaches it);
    NL-only scenarios have none → unbound (route them to the LLM engine instead). httpx only, no browser."""

    name = "api"

    async def run(self, scenario: dict, *, base_url: str) -> EngineResult:
        req = scenario.get("request")
        if not (base_url and isinstance(req, dict) and req.get("path")):
            return EngineResult(self.name, ran=False,
                                note="no executable request binding (need OpenAPI/LLM) or no base_url")
        import httpx
        method = str(req.get("method", "GET")).upper()
        url = base_url.rstrip("/") + "/" + str(req["path"]).lstrip("/")
        expect = int(req.get("expect_status", 0))
        outcomes: list[StepOutcome] = []
        try:
            async with httpx.AsyncClient(timeout=30, transport=_transport) as client:
                resp = await client.request(method, url, json=req.get("json"))
        except Exception as exc:  # noqa: BLE001 — a transport failure is a real (Environment) failure to triage
            return EngineResult(self.name, ran=True,
                                outcomes=[StepOutcome(False, f"{method} {url}: request failed ({exc})")])
        # status conformance: an explicit expect wins; else any non-5xx is acceptable
        ok_status = (resp.status_code == expect) if expect else (resp.status_code < 500)
        outcomes.append(StepOutcome(ok_status,
                        "" if ok_status else f"{method} {url}: status {resp.status_code} (expected {expect or '<500'})"))
        # content conformance: a JSON content-type must parse
        if "json" in resp.headers.get("content-type", ""):
            try:
                resp.json()
            except ValueError:
                outcomes.append(StepOutcome(False, f"{method} {url}: malformed JSON body"))
        return EngineResult(self.name, ran=True, outcomes=outcomes)


class _StubEngine:
    """A registered-but-unbuilt engine: routes correctly, reports unbound (never a fake pass)."""

    def __init__(self, name: str, need: str) -> None:
        self.name, self._need = name, need

    async def run(self, scenario: dict, *, base_url: str) -> EngineResult:
        return EngineResult(self.name, ran=False, note=f"{self.name} engine not built yet — needs {self._need}")


ENGINES: dict[str, RunnerEngine] = {
    "api": ApiEngine(),
    "browser": _StubEngine("browser", "Playwright + a browser binary in the image"),
    "llm": _StubEngine("llm", "a model provider to translate NL steps into actions"),
}

_UI = {"ui", "e2e", "browser", "web", "frontend"}
_API = {"api", "rest", "http", "service", ""}


def select_engine(scenario: dict) -> str:
    """Route a scenario to an engine by its declared `methodology` (the nature of the test)."""
    m = str(scenario.get("methodology") or "api").lower()
    if m in _UI:
        return "browser"
    if m in _API:
        return "api"
    return "llm"
