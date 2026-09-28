"""Route-by-nature engine selection + the engine registry."""

from __future__ import annotations

from test_executor.runners.base import RunnerEngine
from test_executor.runners.engines import ApiEngine, BrowserEngine, LlmEngine

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
