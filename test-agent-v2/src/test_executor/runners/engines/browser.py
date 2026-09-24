"""BrowserEngine — drive a UI/E2E scenario through a BrowserDriver (real Playwright chromium, lazy) or
an injected test fake, with a pre-scenario login plan."""

from __future__ import annotations

import contextlib
from typing import Protocol

from test_executor.runners.base import EngineResult, StepOutcome, _same_site, log
from test_executor.runners.translate import _BROWSER_TRANSLATE_SYSTEM, BrowserPlan, _llm_translate


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
    from test_executor import (
        runners,  # test seam: runners._browser_driver (patched in tests), read at call time
    )
    if runners._browser_driver is not None:
        return runners._browser_driver
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
                  spec: dict | None = None, path_vars: dict | None = None) -> EngineResult:  # spec/path_vars: API-only
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
            log.warning("exec browser run failed: %s", exc)  # full detail server-side only (may include a filled value)
            outcomes.append(StepOutcome(False, f"browser run failed: {type(exc).__name__}"))
        finally:
            with contextlib.suppress(Exception):
                await driver.close()
        return EngineResult(self.name, ran=True, outcomes=outcomes)
