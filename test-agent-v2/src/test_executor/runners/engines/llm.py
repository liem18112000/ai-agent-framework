"""LlmEngine — make a natural-language scenario executable: one LLM call translates it into a
structured request (grounded on the OpenAPI catalog when present), then delegate to ApiEngine."""

from __future__ import annotations

from test_executor.runners.base import EngineResult
from test_executor.runners.engines.api import ApiEngine
from test_executor.runners.translate import (
    _TRANSLATE_SYSTEM,
    RequestPlan,
    _llm_translate,
    _request_from_plan,
)


class LlmEngine:
    """Make a natural-language scenario executable: one LLM call translates it into a structured
    request (the same shape ApiEngine runs), then delegate execution to ApiEngine. Unbound when no
    provider/base_url is configured, or when the model can't produce a concrete request."""

    name = "llm"

    async def run(self, scenario: dict, *, base_url: str, auth: object = None,
                  spec: dict | None = None, path_vars: dict | None = None) -> EngineResult:
        req = scenario.get("request")
        if isinstance(req, dict) and req.get("path"):        # already bound → just execute
            return await ApiEngine().run(scenario, base_url=base_url, auth=auth, spec=spec, path_vars=path_vars)
        from common.adk.model import model_configured
        if not (base_url and model_configured()):
            return EngineResult(self.name, ran=False,
                                note="no provider/base_url — needs a model provider to translate the scenario")
        plan = await self._translate(scenario, spec=spec)
        if not plan or not plan.get("path"):
            return EngineResult(self.name, ran=False, note="the model could not translate this scenario to a request")
        res = await ApiEngine().run({**scenario, "request": _request_from_plan(plan)},
                                    base_url=base_url, auth=auth, spec=spec, path_vars=path_vars)
        return EngineResult(self.name, ran=res.ran, outcomes=res.outcomes, note=res.note)

    async def _translate(self, scenario: dict, *, spec: dict | None = None) -> dict | None:
        # Pillar 3: when the target's OpenAPI is available, ground the translation on its real operations.
        catalog = ""
        if isinstance(spec, dict) and spec.get("ops"):
            from test_executor.openapi import operation_catalog
            catalog = operation_catalog(spec["ops"])
        return await _llm_translate(scenario, system=_TRANSLATE_SYSTEM, schema=RequestPlan,
                                    output_key="request", catalog=catalog)
