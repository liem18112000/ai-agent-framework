"""I8 gate (C1/D10) — all ADK-model construction lives in `common/adk/providers/` only.

A structural guard: `LiteLlm(...)` and `google.adk.models` imports must appear nowhere in `src/`
except under `common/adk/providers/`. Keeps the "one seam for model access" invariant enforced in CI,
not just by review. Also asserts the Gemini backend stays scrubbed.
"""

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
