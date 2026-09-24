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
"""

from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass, field
from typing import Protocol

from pydantic import BaseModel

from common.monitoring import get_logger

log = get_logger("exec.runners")

_MAX_RESPONSE_BYTES = 8 * 1024 * 1024  # cap a SUT response body read into RAM (OOM guard on the 2Gi agent)


def _same_site(url: str, base_url: str) -> bool:
    """Per-run egress allow-list: True iff `url` is http(s) on the SAME host as `base_url`. The executor
    legitimately targets INTERNAL / localhost test envs, so `common.net.host_blocked` (which blocks
    private/loopback) is the wrong guard here — the run must only reach its own base_url host, which is
    what blocks metadata / file:// / foreign-host pivots that scenario text could otherwise reach."""
    import httpx
    try:
        u = httpx.URL(url)
    except Exception:  # noqa: BLE001 — a malformed URL is not same-site
        return False
    return u.scheme in ("http", "https") and bool(u.host) and u.host == httpx.URL(base_url).host

#: Test seam — an httpx transport override (MockTransport/ASGITransport) so ApiEngine runs offline.
_transport = None

#: Test seam — a BrowserDriver override so BrowserEngine runs offline (no real browser binary).
_browser_driver = None


@dataclass
class StepOutcome:
    ok: bool
    message: str = ""      # failure detail (feeds triage) when not ok
    flaky: bool = False


@dataclass
class EngineResult:
    engine: str
    ran: bool                                        # False = unbound (no executable binding / no provider)
    outcomes: list[StepOutcome] = field(default_factory=list)
    note: str = ""

    @property
    def passed(self) -> bool:
        return self.ran and all(o.ok for o in self.outcomes)


class RunnerEngine(Protocol):
    name: str

    async def run(self, scenario: dict, *, base_url: str, auth: object = None,
                  spec: dict | None = None) -> EngineResult: ...


class ApiEngine:
    """Deterministic API execution: run the scenario's structured request against `base_url` and check
    conformance (status class + JSON validity). A scenario carries an executable binding under
    `request` = {method?, path, json?, expect_status?} (a future TPD or a translator attaches it);
    NL-only scenarios have none → unbound (route them to the LLM engine instead). httpx only, no browser."""

    name = "api"

    async def run(self, scenario: dict, *, base_url: str, auth: object = None,
                  spec: dict | None = None) -> EngineResult:
        req = scenario.get("request")
        if not (base_url and isinstance(req, dict) and req.get("path")):
            return EngineResult(self.name, ran=False,
                                note="no executable request binding (need OpenAPI/LLM) or no base_url")
        import httpx
        method = str(req.get("method", "GET")).upper()
        url = base_url.rstrip("/") + "/" + str(req["path"]).lstrip("/")
        where = f"{method} {req['path']}"  # host-free: keeps any base_url userinfo/creds out of the ledger + reply
        if not _same_site(url, base_url):  # egress allow-list — the request must stay on the run's base_url host
            return EngineResult(self.name, ran=True, outcomes=[StepOutcome(False, f"{where}: blocked off-site target")])
        expect = int(req.get("expect_status", 0))
        outcomes: list[StepOutcome] = []
        try:
            headers = getattr(auth, "headers", None) or None   # AuthContext.headers (bearer), if any
            async with httpx.AsyncClient(timeout=30, transport=_transport) as client, \
                    client.stream(method, url, headers=headers, **_send_kwargs(req)) as resp:
                declared = resp.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > _MAX_RESPONSE_BYTES:
                    return EngineResult(self.name, ran=True, outcomes=[StepOutcome(
                        False, f"{where}: response exceeds {_MAX_RESPONSE_BYTES} bytes")])
                body = bytearray()
                async for chunk in resp.aiter_bytes():
                    body += chunk
                    if len(body) > _MAX_RESPONSE_BYTES:  # cap before the body OOMs the 2Gi container
                        return EngineResult(self.name, ran=True, outcomes=[StepOutcome(
                            False, f"{where}: response exceeds {_MAX_RESPONSE_BYTES} bytes")])
                text = bytes(body).decode(resp.charset_encoding or "utf-8", errors="replace")
                status, ctype = resp.status_code, resp.headers.get("content-type", "")
        except Exception as exc:  # noqa: BLE001 — a transport failure is a real (Environment) failure to triage
            log.warning("exec api %s failed: %s", where, exc)  # full detail server-side only
            return EngineResult(self.name, ran=True,
                                outcomes=[StepOutcome(False, f"{where}: request failed ({type(exc).__name__})")])
        # status conformance: an explicit expect wins; else any non-5xx is acceptable
        ok_status = (status == expect) if expect else (status < 500)
        outcomes.append(StepOutcome(ok_status,
                        "" if ok_status else f"{where}: status {status} (expected {expect or '<500'})"))
        # content conformance: a JSON content-type must parse
        if "json" in ctype:
            try:
                json.loads(text)
            except ValueError:
                outcomes.append(StepOutcome(False, f"{where}: malformed JSON body"))
        # oracle: the expected end-state must appear in the response (the scenario's `Then`)
        want = str(req.get("expect_contains", ""))
        if want and want not in text:
            outcomes.append(StepOutcome(False, f"{where}: response missing expected {want!r}"))
        # Pillar 3: OpenAPI conformance oracle — status + response-schema declared by the spec
        if isinstance(spec, dict) and spec.get("spec"):
            from test_executor.openapi import conformance_failures, match_operation
            op = match_operation(spec.get("ops") or [], method, str(req["path"]).split("?", 1)[0])
            if op is not None:
                for msg in conformance_failures(spec["spec"], op, status=status, body_text=text, content_type=ctype):
                    outcomes.append(StepOutcome(False, f"{where}: {msg}"))
        return EngineResult(self.name, ran=True, outcomes=outcomes)


class BrowserDriver(Protocol):
    """The browser BrowserEngine drives — one Protocol so the real Playwright driver and the offline
    test fake are interchangeable (the browser twin of ApiEngine's `_transport` seam)."""

    async def goto(self, url: str) -> None: ...
    async def act(self, action: str, selector: str = "", value: str = "") -> None: ...
    async def text(self) -> str: ...
    async def close(self) -> None: ...


class PlaywrightDriver:
    """Real driver — Playwright chromium (lazy import). Enable in the image with
    `pip install playwright && playwright install chromium`; absent → BrowserEngine reports unbound."""

    def __init__(self) -> None:
        self._pw = self._browser = self._page = None

    async def _ensure(self):
        if self._page is None:
            from playwright.async_api import async_playwright
            self._pw = await async_playwright().start()
            # --no-sandbox is required to run chromium as the non-root container user; --disable-dev-shm-usage
            # avoids crashes on the small /dev/shm containers get. See Dockerfile INSTALL_BROWSER.
            self._browser = await self._pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
            self._page = await self._browser.new_page()
        return self._page

    async def goto(self, url: str) -> None:
        await (await self._ensure()).goto(url)

    async def act(self, action: str, selector: str = "", value: str = "") -> None:
        # Navigation is NOT an `act` — it flows through `goto()` so BrowserEngine's egress allow-list gates it.
        page = await self._ensure()
        if action == "click":
            await page.click(selector)
        elif action == "fill":
            await page.fill(selector, value)

    async def text(self) -> str:
        return await (await self._ensure()).inner_text("body")

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()


def _get_browser_driver():
    """The injected test driver, else a real PlaywrightDriver when the package is importable, else None."""
    if _browser_driver is not None:
        return _browser_driver
    import importlib.util
    return PlaywrightDriver() if importlib.util.find_spec("playwright") is not None else None


async def _do_login(driver, login: dict, *, base_url: str) -> None:
    """Run a browser login plan before the scenario: open the login page (same-host), fill the
    username/password fields, submit. Best-effort — a missing selector/cred just skips that action."""
    await driver.goto(base_url.rstrip("/") + "/" + str(login.get("path", "")).lstrip("/"))
    if login.get("user_selector") and login.get("username"):
        await driver.act("fill", login["user_selector"], login["username"])
    if login.get("pass_selector") and login.get("password"):
        await driver.act("fill", login["pass_selector"], login["password"])
    if login.get("submit_selector"):
        await driver.act("click", login["submit_selector"])


class BrowserEngine:
    """Drive a UI/E2E scenario via a BrowserDriver. The scenario's structured browser plan
    (`scenario["browser"]` = {url_path, steps:[{action, selector, value}], expect_text}) is run and the
    final page is asserted to contain `expect_text` (its Gherkin `Then`). A natural-language UI scenario
    with no plan is translated by one LLM call (BrowserPlan) — the browser twin of LlmEngine."""

    name = "browser"

    async def run(self, scenario: dict, *, base_url: str, auth: object = None,
                  spec: dict | None = None) -> EngineResult:     # spec is API-only; browser ignores it
        plan = scenario.get("browser")
        if not plan and base_url:                            # NL UI scenario → translate via the LLM
            from common.adk.model import model_configured
            if model_configured():
                plan = await _llm_translate(scenario, system=_BROWSER_TRANSLATE_SYSTEM,
                                            schema=BrowserPlan, output_key="browser")
        if not (base_url and isinstance(plan, dict) and (plan.get("url_path") or plan.get("steps"))):
            return EngineResult(self.name, ran=False,
                                note="no browser plan / base_url and no provider to translate the scenario")
        driver = _get_browser_driver()   # ponytail: fresh browser per scenario; pool if throughput matters
        if driver is None:
            return EngineResult(self.name, ran=False,
                                note="browser engine needs Playwright (pip install playwright && playwright install chromium)")
        import httpx
        outcomes: list[StepOutcome] = []
        try:
            login = getattr(auth, "login", None)     # AuthContext.login — a UI login plan, if configured
            if isinstance(login, dict):
                await _do_login(driver, login, base_url=base_url)
            await driver.goto(base_url.rstrip("/") + "/" + str(plan.get("url_path", "")).lstrip("/"))
            for step in plan.get("steps", []):
                action = step.get("action", "")
                if action == "goto":  # a nav step's target is untrusted scenario text — pin it to base_url's host
                    target = str(httpx.URL(base_url).join(step.get("value", "")))
                    if not _same_site(target, base_url):
                        outcomes.append(StepOutcome(False, f"blocked off-site navigation to {step.get('value', '')!r}"))
                        continue
                    await driver.goto(target)
                else:
                    await driver.act(action, step.get("selector", ""), step.get("value", ""))
            want = str(plan.get("expect_text", ""))
            ok = (want in await driver.text()) if want else True
            outcomes.append(StepOutcome(ok, "" if ok else f"page missing expected text {want!r}"))
        except Exception as exc:  # noqa: BLE001 — a browser/driver failure is a real failure to triage
            outcomes.append(StepOutcome(False, f"browser run failed: {exc}"))
        finally:
            with contextlib.suppress(Exception):
                await driver.close()
        return EngineResult(self.name, ran=True, outcomes=outcomes)


class RequestPlan(BaseModel):
    """The LLM's structured translation of a scenario into one executable HTTP request + its oracle."""

    method: str = "GET"
    path: str = ""
    body: dict | None = None
    expect_status: int = 0
    expect_contains: str = ""


_TRANSLATE_SYSTEM = (
    "You translate ONE test scenario into a single executable HTTP request against a REST API. "
    "Given the scenario's title, description and preconditions, output the request that exercises it: "
    "the HTTP method, a path relative to the base URL (leading '/'), an optional JSON body, and the "
    "expected HTTP status. Set expect_contains ONLY when the scenario itself states a concrete value the "
    "response must contain (its Gherkin 'Then'); if the scenario names no expected content, leave it "
    "EMPTY — do not invent a substring, or you assert something the endpoint never promised. Output only "
    "the structured fields. If you cannot infer a concrete request, return an empty path."
)


class BrowserStep(BaseModel):
    action: str = ""      # goto | click | fill
    selector: str = ""    # a CSS selector for click/fill
    value: str = ""       # the text to fill, or a URL for goto


class BrowserPlan(BaseModel):
    """The LLM's structured translation of a UI scenario into a browser interaction + its oracle."""

    url_path: str = ""                                # path relative to the base URL (leading '/')
    steps: list[BrowserStep] = []                     # ordered click/fill interactions
    expect_text: str = ""                             # text the final page must contain (the 'Then')


_BROWSER_TRANSLATE_SYSTEM = (
    "You translate ONE UI test scenario into a single browser interaction against a web app. Given the "
    "scenario's title, description and preconditions, output: the path to open (relative to the base URL, "
    "leading '/'), an ordered list of steps (each an action 'click' or 'fill' with a CSS selector, and a "
    "value for 'fill'), and a short substring the final page must contain to prove the scenario's expected "
    "end-state (its Gherkin 'Then'). Output only the structured fields. If you cannot infer a concrete "
    "interaction, return an empty url_path."
)


def _scenario_task(scenario: dict, *, extra: str = "", catalog: str = "") -> str:
    parts = [f"title: {scenario.get('title', '')}", f"kind: {scenario.get('kind', '')}"]
    if scenario.get("description"):
        parts.append(f"description: {scenario['description']}")
    pre = scenario.get("preconditions") or []
    if pre:
        parts.append("preconditions: " + "; ".join(map(str, pre)))
    if extra:                                        # heal feedback: the prior failure to correct
        parts.append(extra)
    if catalog:                                      # Pillar 3: ground the call on the target's REAL operations
        parts.append("Choose the ONE operation below that matches and use its EXACT method + path "
                     "(fill path params with realistic values):\n" + catalog)
    return "\n".join(parts)


def _request_from_plan(plan: dict) -> dict:
    """A RequestPlan dict → the ApiEngine `request` shape (shared by LlmEngine + heal)."""
    return {"method": plan.get("method", "GET"), "path": plan.get("path", ""), "json": plan.get("body"),
            "expect_status": plan.get("expect_status", 0), "expect_contains": plan.get("expect_contains", "")}


def _send_kwargs(req: dict) -> dict:
    """The httpx body kwargs for a request: a multipart file upload when the scenario supplies an
    `upload` ({field, path, filename?, content_type?, data?}), else a JSON body. The file is read into
    memory (ponytail: fine for test fixtures like an import zip; stream it if a huge upload is ever needed).
    A missing file raises here and is caught by the caller as a real request failure."""
    up = req.get("upload")
    if isinstance(up, dict) and up.get("path"):
        import os
        with open(up["path"], "rb") as fh:
            content = fh.read()
        files = {up.get("field", "file"): (up.get("filename") or os.path.basename(up["path"]),
                                           content, up.get("content_type") or "application/octet-stream")}
        return {"files": files, "data": up.get("data") or None}   # extra form fields alongside the file
    return {"json": req.get("json")}


async def _llm_translate(scenario: dict, *, system: str, schema, output_key: str,
                         extra: str = "", catalog: str = "") -> dict | None:
    """One structured-output LLM call: translate a scenario into `schema` (an API request or a browser
    plan), returning the validated dict or None on degrade. `extra` appends heal feedback (the prior
    failure to fix); `catalog` grounds the call on the target's real OpenAPI operations (Pillar 3).
    Shared by LlmEngine, BrowserEngine, and heal()."""
    from common.adk.model import agent_model
    from common.testplan.llm.adk import build_generator_agent, run_json_agent
    agent = build_generator_agent(name="exec_translate", system=system, output_schema=schema,
                                  output_key=output_key, model=agent_model())
    return await run_json_agent(agent, output_key=output_key,
                                user=_scenario_task(scenario, extra=extra, catalog=catalog))


async def heal(scenario: dict, failure_message: str, *, base_url: str) -> tuple[dict | None, EngineResult]:
    """Propose a corrected plan for a FAILED scenario (one LLM call with the failure fed back) and
    re-run it against the live SUT to verify. NOTE: the proposed plan IS executed once here to verify it
    — bounded to the run's `base_url` host by the engines' egress allow-list (`_same_site`), exactly as
    `run_suite` already executes scenarios against this test env. What's human-gated is the PATCH: the
    proposal is returned for a Yes/No and is never persisted/applied to retarget future runs (no silent
    retarget). Routes by the scenario's nature: browser → BrowserPlan, else → RequestPlan."""
    feedback = (f"The previous attempt FAILED with: {failure_message}. Produce a CORRECTED plan that "
                "fixes the failing selector / wait / request so the scenario passes.")
    engine_name = select_engine(scenario)
    if engine_name == "browser":
        plan = await _llm_translate(scenario, system=_BROWSER_TRANSLATE_SYSTEM, schema=BrowserPlan,
                                    output_key="browser", extra=feedback)
        healed = {**scenario, "browser": plan} if plan else scenario
    else:
        plan = await _llm_translate(scenario, system=_TRANSLATE_SYSTEM, schema=RequestPlan,
                                    output_key="request", extra=feedback)
        healed = {**scenario, "request": _request_from_plan(plan)} if plan else scenario
    return plan, await ENGINES[engine_name].run(healed, base_url=base_url)


class LlmEngine:
    """Make a natural-language scenario executable: one LLM call translates it into a structured
    request (the same shape ApiEngine runs), then delegate execution to ApiEngine. Unbound when no
    provider/base_url is configured, or when the model can't produce a concrete request."""

    name = "llm"

    async def run(self, scenario: dict, *, base_url: str, auth: object = None,
                  spec: dict | None = None) -> EngineResult:
        req = scenario.get("request")
        if isinstance(req, dict) and req.get("path"):        # already bound → just execute
            return await ApiEngine().run(scenario, base_url=base_url, auth=auth, spec=spec)
        from common.adk.model import model_configured
        if not (base_url and model_configured()):
            return EngineResult(self.name, ran=False,
                                note="no provider/base_url — needs a model provider to translate the scenario")
        plan = await self._translate(scenario, spec=spec)
        if not plan or not plan.get("path"):
            return EngineResult(self.name, ran=False, note="the model could not translate this scenario to a request")
        res = await ApiEngine().run({**scenario, "request": _request_from_plan(plan)},
                                    base_url=base_url, auth=auth, spec=spec)
        return EngineResult(self.name, ran=res.ran, outcomes=res.outcomes, note=res.note)

    async def _translate(self, scenario: dict, *, spec: dict | None = None) -> dict | None:
        # Pillar 3: when the target's OpenAPI is available, ground the translation on its real operations.
        catalog = ""
        if isinstance(spec, dict) and spec.get("ops"):
            from test_executor.openapi import operation_catalog
            catalog = operation_catalog(spec["ops"])
        return await _llm_translate(scenario, system=_TRANSLATE_SYSTEM, schema=RequestPlan,
                                    output_key="request", catalog=catalog)


ENGINES: dict[str, RunnerEngine] = {
    "api": ApiEngine(),
    "browser": BrowserEngine(),
    "llm": LlmEngine(),
}

_UI = {"ui", "e2e", "browser", "web", "frontend"}
_API = {"api", "rest", "http", "service", ""}


def select_engine(scenario: dict) -> str:
    """Route a scenario to an engine by its declared `methodology` (the nature of the test).

    An `api` scenario runs on ApiEngine only when it carries a structured `request`; a natural-language
    api scenario (no binding — the TPD default) routes to the LLM engine so it is translated → executed
    rather than reported unbound."""
    m = str(scenario.get("methodology") or "api").lower()
    if m in _UI:
        return "browser"
    if m in _API:
        req = scenario.get("request")
        return "api" if isinstance(req, dict) and req.get("path") else "llm"
    return "llm"
