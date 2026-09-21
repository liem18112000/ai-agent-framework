"""`JevProvider` — the one `DecisionProvider` impl, wrapping JEV's REST/SDK.

JEV is early-access with no stable public endpoint yet, so the three primitives are a MARKED STUB:
``is_configured()`` is True only when ``TYPESAFE_API_KEY`` is set, and no environment we run sets it,
so the stub bodies are never reached (the offline suite guards on ``is_configured()``). No network lib
is imported at module load — the real transport is wired lazily inside ``_call`` when JEV ships.
"""

from __future__ import annotations

import os

from common.adk.providers.decision import Verdict


class JevProvider:
    name = "jev"

    def is_configured(self) -> bool:
        """True only when ``TYPESAFE_API_KEY`` is set — the guard that keeps the stub off every path
        (no key in any current environment → callers keep their LLM path)."""
        return bool(os.environ.get("TYPESAFE_API_KEY", "").strip())

    def choice(self, state: str, options: list[str], instructions: str) -> Verdict:
        return self._call("choice", state=state, options=options, instructions=instructions)

    def score(self, state: str, instructions: str, levels: list[str]) -> Verdict:
        return self._call("score", state=state, instructions=instructions, levels=levels)

    def noul(self, state: str, statement: str) -> Verdict:
        return self._call("noul", state=state, statement=statement)

    def _call(self, primitive: str, **payload) -> Verdict:
        # ponytail: JEV is early-access — the real REST/SDK transport (and its lazily-imported HTTP
        # client) is wired HERE when it leaves early-access and we can calibrate on our goldens. Until
        # then is_configured() is False in every environment, so this never executes.
        raise NotImplementedError(
            "JevProvider transport is a stub until JEV leaves early-access; TYPESAFE_API_KEY is not "
            "set in any current environment (is_configured() gates every caller)."
        )
