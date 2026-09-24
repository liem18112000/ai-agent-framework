"""LLM translation + the shared request helpers: the structured plan models, the translate/heal system
prompts, path-var substitution, the multipart body builder, and heal().

Engines call these; heal() is here too (it produces a corrected plan and re-runs it) but imports the
engine registry lazily so this module stays a leaf of the engine graph.
"""

from __future__ import annotations

from pydantic import BaseModel

from test_executor.runners.base import EngineResult


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


def _subst_path(path: str, path_vars: dict | None) -> str:
    """Substitute `{var}` templates in a request path from the environment's `path_vars` (e.g. a grounded
    OpenAPI path `/api/{tenant-id}/import-jobs/upload-zip` → the env's real tenant). Var names may contain
    hyphens (OpenAPI uses `{tenant-id}`). An UNKNOWN template is left literal — it surfaces as a real 404,
    never a silent pass. No path_vars / no template → returns the path unchanged."""
    if not path_vars or "{" not in path:
        return path
    import re
    return re.sub(r"\{([\w-]+)\}", lambda m: str(path_vars.get(m.group(1), m.group(0))), path)


def _send_kwargs(req: dict) -> dict:
    """The httpx body kwargs for a request: a multipart file upload when the scenario supplies an
    `upload` ({field, content, filename?, content_type?, data?}), else a JSON body. The bytes come from
    inline `content` only (resolved from a bank TestData fixture by run_suite) — never a local filesystem
    path, so scenario/ticket-derived content can't turn into an arbitrary-file read + exfil to the SUT."""
    up = req.get("upload")
    if isinstance(up, dict) and up.get("content") is not None:
        files = {up.get("field", "file"): (up.get("filename") or "upload.bin", up["content"],
                                           up.get("content_type") or "application/octet-stream")}
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
    from test_executor.runners.select import (  # lazy: keeps this module a leaf
        ENGINES,
        select_engine,
    )
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
