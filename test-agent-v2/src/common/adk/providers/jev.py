"""`JevProvider` — the one `DecisionProvider` impl, wrapping the TypeSafe System-1 SDK.

Transport is the official ``typesafe-sdk`` (https://docs.typesafe.ai/sdk/python): one blocking
``TypeSafeClient.system_one(state, questions)`` per decision, mapping Choice/Score/Noul onto our three
primitives. The SDK is LAZY-imported inside ``_call`` (install the ``jev`` extra) so this module still
loads with the package absent and the offline suite never imports a network lib. ``is_configured()`` is
gated on ``TYPESAFE_API_KEY`` — unset → callers keep their existing LLM path (the port is default OFF).

UNVERIFIED against a live response (JEV is early-access): the docs pin ``.choice/.score/.noul`` but do
NOT document a confidence or probability field, and leave the ``Score`` encoding ("ranked score") loose.
So confidence/probs are probed defensively (``_conf``/``_probs``) and the score is normalised to the
0–1 float the port promises (``_score01``). Confidence falls back to ``TYPESAFE_DEFAULT_CONFIDENCE``
(default 1.0 — enabling this backend is an explicit "trust JEV" opt-in; lower it, or raise the cascade's
``TPD_DECISION_CONF_MIN``, to keep the LLM judge in the loop). Re-check all three once JEV ships GA.
"""

from __future__ import annotations

import os

from common.adk.providers.decision import Verdict

_QKEY = "q"  # single-question calls: one key in, one key out


class JevProvider:
    name = "jev"

    def is_configured(self) -> bool:
        return bool(os.environ.get("TYPESAFE_API_KEY", "").strip())

    def choice(self, state: str, options: list[str], instructions: str) -> Verdict:
        return self._call("choice", state, options=options, instructions=instructions)

    def score(self, state: str, instructions: str, levels: list[str]) -> Verdict:
        return self._call("score", state, instructions=instructions, levels=levels)

    def noul(self, state: str, statement: str) -> Verdict:
        return self._call("noul", state, statement=statement)

    def _call(self, primitive: str, state: str, **spec) -> Verdict:
        from typesafe_sdk import Choice, Noul, Score, TypeSafeClient

        question = {
            "choice": lambda: Choice(instructions=spec["instructions"], criteria={o: None for o in spec["options"]}),
            "score": lambda: Score(instructions=spec["instructions"], criteria=list(spec["levels"])),
            "noul": lambda: Noul(instructions=spec["statement"]),
        }[primitive]()
        with TypeSafeClient() as client:
            result = client.system_one(state=state, questions={_QKEY: question})
        return _verdict(primitive, result, spec)


def _verdict(primitive: str, result, spec: dict) -> Verdict:
    """Map one System-1 result row onto a typed ``Verdict`` (value + defensive probs/confidence)."""
    if primitive == "choice":
        r = result.choices[_QKEY]
        return Verdict(value=r.choice, probs=_probs(r), confidence=_conf(r))
    if primitive == "noul":
        r = result.nouls[_QKEY]
        return Verdict(value=bool(r.noul), probs=_probs(r), confidence=_conf(r))
    r = result.scores[_QKEY]
    return Verdict(value=_score01(r.score, spec["levels"]), probs=_probs(r), confidence=_conf(r))


def _conf(r) -> float:
    """JEV's calibrated confidence if the response carries one; else the opt-in default."""
    for name in ("confidence", "calibrated_confidence", "probability"):
        v = getattr(r, name, None)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
    return float(os.environ.get("TYPESAFE_DEFAULT_CONFIDENCE", "1.0"))


def _probs(r) -> dict[str, float] | None:
    """Per-outcome distribution if present (noul reads ``probs['true']``); else None → bool fallback."""
    v = getattr(r, "probs", None) or getattr(r, "probabilities", None)
    return {str(k): float(x) for k, x in v.items()} if isinstance(v, dict) else None


def _score01(raw, levels: list[str]) -> float:
    """Normalise a ``Score`` result to a 0–1 float. Encoding is unverified, so cover the three plausible
    shapes: already-0–1 float (pass through), an ordinal rank/index (÷ span), or a level string (its
    position ÷ span). ``bool`` is guarded first (it is an ``int`` subclass)."""
    span = max(len(levels) - 1, 1)
    if isinstance(raw, bool):
        return 1.0 if raw else 0.0
    if isinstance(raw, (int, float)):
        f = float(raw)
        return f if 0.0 <= f <= 1.0 else max(0.0, min(1.0, f / span))
    if raw in levels:
        return levels.index(raw) / span
    return 0.0


if __name__ == "__main__":  # ponytail: one runnable check on the only non-trivial logic (mapping)
    L = ["low", "medium", "high"]
    assert _score01(0.42, L) == 0.42
    assert _score01(2, L) == 1.0 and _score01(1, ["no", "yes"]) == 1.0
    assert _score01("high", L) == 1.0 and _score01("low", L) == 0.0
    assert _score01(True, L) == 1.0 and _score01("weird", L) == 0.0

    class _R:
        choice, confidence, probs = "b", 0.77, {"true": 0.9}
    v = _verdict("choice", type("X", (), {"choices": {_QKEY: _R()}})(), {})
    assert v.value == "b" and v.confidence == 0.77 and v.probs == {"true": 0.9}

    class _N:
        noul = 1
    v = _verdict("noul", type("X", (), {"nouls": {_QKEY: _N()}})(), {})
    assert v.value is True and v.confidence == 1.0 and v.probs is None  # default conf, no probs
    print("ok")
