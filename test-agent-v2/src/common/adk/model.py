"""Claude Sonnet 5 on Vertex via ADK's LiteLlm — one place, with the v1 gotchas preserved.

`claude_llm()` returns a configured `LiteLlm` when Vertex is configured, else `None` (the master
"no LLM → use the heuristic path" signal every v1 factory already keys off — invariant I7).

Gotchas carried from `common/llm/vertex.py` (invariant I5):
  - thinking DISABLED so the whole max_tokens budget is output (tight JSON contracts truncate otherwise);
  - max_tokens set per call (the 1500→6000 fix that stopped mid-array JSON truncation).
[verify @2.x]: confirm LiteLlm forwards `thinking`/`max_tokens` to the Vertex-Anthropic path with a
live call in A1 before trusting it in prod.
"""

from __future__ import annotations

from common.adk.config import get_config
from common.llm.vertex import vertex_config


def agent_model(*, max_tokens: int | None = None):
    """The model for an ADK `LlmAgent`, per `Config.model_backend` (E2).

    Returns a `LiteLlm` (Claude — default), a Gemini model-id string, or `None` (Vertex unset →
    the caller uses the heuristic path, I7). This is the backend-agnostic entry point; `claude_llm`
    stays the Claude-specific builder.
    """
    cfg = get_config()
    if cfg.model_backend == "gemini":
        return cfg.gemini_model  # ADK LlmAgent accepts a Gemini model-id string directly
    return claude_llm(max_tokens=max_tokens or cfg.default_max_tokens)


def claude_llm(*, max_tokens: int = 6000):
    """A LiteLlm for Claude-on-Vertex, or None when VERTEX_* is unset (→ heuristic fallback)."""
    cfg = vertex_config()
    if cfg is None:
        return None
    project, location, model = cfg
    from google.adk.models.lite_llm import LiteLlm

    return LiteLlm(
        model=f"vertex_ai/{model}",
        vertex_project=project,
        vertex_location=location,
        max_tokens=max_tokens,
        thinking={"type": "disabled"},
    )
