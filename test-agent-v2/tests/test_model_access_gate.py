"""I8 gate (C1/D10) — all ADK-model construction lives in `common/adk/providers/` only."""

from __future__ import annotations

import pathlib
import re

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
_PROVIDERS = _SRC / "common" / "adk" / "providers"
_MODEL_CONSTRUCT = re.compile(r"\bLiteLlm\(|(?:from|import)\s+google\.adk\.models")


def _py_files():
    return [p for p in _SRC.rglob("*.py") if "__pycache__" not in p.parts]


def test_model_construction_only_in_providers():
    offenders = []
    for p in _py_files():
        if _PROVIDERS in p.parents:
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if _MODEL_CONSTRUCT.search(line):
                offenders.append(f"{p.relative_to(_SRC)}:{i}: {line.strip()}")
    assert not offenders, "ADK model construction (I8) must live only in common/adk/providers/:\n" + "\n".join(offenders)


def test_gemini_backend_is_scrubbed():
    hits = []
    for p in _py_files():
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if "gemini" in line.lower():
                hits.append(f"{p.relative_to(_SRC)}:{i}: {line.strip()}")
    assert not hits, "Gemini references must be gone from src/ (C1):\n" + "\n".join(hits)


def test_fast_tier_resolves_to_vertex_model_fast_or_falls_back(monkeypatch):
    """`tier="fast"` uses VERTEX_MODEL_FAST when set, else the default model (so the fast tier is inert
    until an operator configures it — zero behaviour change by default)."""
    from common.adk.providers.vertex_claude import VertexClaudeProvider as P

    monkeypatch.delenv("VERTEX_MODEL_FAST", raising=False)
    assert P._tier_model("default-model", "default") == "default-model"
    assert P._tier_model("default-model", "fast") == "default-model"  # unset → fall back
    monkeypatch.setenv("VERTEX_MODEL_FAST", "fast-model")
    assert P._tier_model("default-model", "fast") == "fast-model"
    assert P._tier_model("default-model", "default") == "default-model"  # default tier ignores it


def test_fast_tier_clamps_max_tokens_to_fast_ceiling(monkeypatch):
    """The fast model (haiku) caps output at 64000 < the 128000 default; tier="fast" must clamp or
    Vertex 400s the request (this killed the assured judge in the first A/B). Default tier passes through."""
    from common.adk.providers.vertex_claude import VertexClaudeProvider as P

    monkeypatch.delenv("VERTEX_MODEL_FAST_MAX_TOKENS", raising=False)
    assert P._cap_max_tokens(128000, "default") == 128000
    assert P._cap_max_tokens(128000, "fast") == 64000
    assert P._cap_max_tokens(1200, "fast") == 1200  # already under the ceiling → unchanged
    monkeypatch.setenv("VERTEX_MODEL_FAST_MAX_TOKENS", "32000")
    assert P._cap_max_tokens(128000, "fast") == 32000
