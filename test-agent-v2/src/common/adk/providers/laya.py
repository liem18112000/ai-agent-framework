"""`LayaProvider` — the local `DecisionProvider`: laya (System-1 decision engine), JEV's open twin.

laya is an in-process torch/transformers library (no server, heavy: multi-GB checkpoints), so instead
of baking torch into every agent image we run it once as a tiny sidecar (`laya_service/`) and talk to
it over HTTP here. Same three primitives as JEV (choice/score/noul); the sidecar returns laya's native
``answers`` shape (README: ``answers[q]["choice"|"score"|"noul"]`` + ``confidence``/``probabilities``).

Select with ``TPD_DECISION_BACKEND=laya``; ``is_configured()`` gates on ``LAYA_URL`` (default OFF, like
JEV, so unconfigured => callers keep their LLM path). Result-field names are pinned to laya's README and
are UNVERIFIED against a pinned release — read defensively; re-check on the first live run.
"""

from __future__ import annotations

import os

from common.adk.providers.decision import Verdict, score01

_QKEY = "q"


class LayaProvider:
    name = "laya"

    def is_configured(self) -> bool:
        return bool(os.environ.get("LAYA_URL", "").strip())

    def choice(self, state: str, options: list[str], instructions: str) -> Verdict:
        a = self._decide(state, {"type": "choice", "instructions": instructions,
                                 "criteria": {o: "" for o in options}})
        return Verdict(value=a.get("choice"), probs=_probs(a), confidence=_conf(a))

    def score(self, state: str, instructions: str, levels: list[str]) -> Verdict:
        a = self._decide(state, {"type": "score", "instructions": instructions, "criteria": list(levels)})
        return Verdict(value=score01(a.get("score"), levels), probs=_probs(a), confidence=_conf(a))

    def noul(self, state: str, statement: str) -> Verdict:
        a = self._decide(state, {"type": "noul", "instructions": statement})
        p = float(a.get("noul", 0.0))
        return Verdict(value=(p >= 0.5), probs={"true": p}, confidence=_conf(a, default=abs(p - 0.5) * 2.0))

    def _decide(self, state: str, question: dict) -> dict:
        import httpx

        url = os.environ["LAYA_URL"].rstrip("/") + "/decide"
        r = httpx.post(url, json={"state": state, "questions": {_QKEY: question}},
                       timeout=float(os.environ.get("LAYA_TIMEOUT", "120")))
        r.raise_for_status()
        return (r.json().get("answers") or {}).get(_QKEY, {})


def _conf(a: dict, default: float | None = None) -> float:
    v = a.get("confidence")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    return default if default is not None else float(os.environ.get("LAYA_DEFAULT_CONFIDENCE", "1.0"))


def _probs(a: dict) -> dict[str, float] | None:
    v = a.get("probabilities") or a.get("distribution")
    return {str(k): float(x) for k, x in v.items()} if isinstance(v, dict) else None
