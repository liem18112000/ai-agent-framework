"""`JevProvider` — the one `DecisionProvider` impl, wrapping the TypeSafe System-1 SDK.

Transport is the official ``typesafe-sdk`` (https://docs.typesafe.ai/sdk/python): one blocking
``TypeSafeClient.system_one(state, questions)`` per decision, mapping Choice/Score/Noul onto our three
primitives. The SDK is LAZY-imported inside ``_call`` (install the ``jev`` extra) so this module still
loads with the package absent and the offline suite never imports a network lib. ``is_configured()`` is
gated on ``TYPESAFE_API_KEY`` — unset → callers keep their existing LLM path (the port is default OFF).

Response shapes are pinned against ``typesafe-sdk`` 0.7.1 ``model_fields``: ``NoulAnswer.noul`` IS
P(true) (a 0–1 float; there is NO separate probs/confidence field) — so noul maps it into
``probs['true']`` and derives ``confidence`` as the calibrated distance from a coin-flip (``|p-0.5|*2``).
``ScoreAnswer``/``ChoiceAnswer`` DO carry ``confidence`` + ``probabilities``, read defensively
(``_conf``/``_probs``); ``Score.score`` is normalised to the 0–1 float the port promises (``_score01``,
encoding still loose). Score/Choice confidence falls back to ``TYPESAFE_DEFAULT_CONFIDENCE`` (default
1.0 — an explicit "trust JEV" opt-in; lower it, or raise the cascade's ``TPD_DECISION_CONF_MIN``, to
keep the LLM judge in the loop). Re-check on any SDK upgrade.
"""

from __future__ import annotations

import os

from common.adk.providers.decision import Verdict, score01

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
        p = float(result.nouls[_QKEY].noul)  # SDK 0.7.1: NoulAnswer.noul IS P(true); no probs/confidence field
        return Verdict(value=(p >= 0.5), probs={"true": p}, confidence=abs(p - 0.5) * 2.0)
    r = result.scores[_QKEY]
    return Verdict(value=score01(r.score, spec["levels"]), probs=_probs(r), confidence=_conf(r))


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


if __name__ == "__main__":  # ponytail: one runnable check on the only non-trivial logic (mapping)
    L = ["low", "medium", "high"]
    assert score01(0.42, L) == 0.42
    assert score01(2, L) == 1.0 and score01(1, ["no", "yes"]) == 1.0
    assert score01("high", L) == 1.0 and score01("low", L) == 0.0
    assert score01(True, L) == 1.0 and score01("weird", L) == 0.0

    class _R:
        choice, confidence, probs = "b", 0.77, {"true": 0.9}
    v = _verdict("choice", type("X", (), {"choices": {_QKEY: _R()}})(), {})
    assert v.value == "b" and v.confidence == 0.77 and v.probs == {"true": 0.9}

    class _N:  # SDK 0.7.1: NoulAnswer.noul IS P(true) → probs carries it; confidence = |p-0.5|*2
        noul = 0.2
    v = _verdict("noul", type("X", (), {"nouls": {_QKEY: _N()}})(), {})
    assert v.value is False and v.probs == {"true": 0.2} and abs(v.confidence - 0.6) < 1e-9

    class _N1:
        noul = 1.0
    v = _verdict("noul", type("X", (), {"nouls": {_QKEY: _N1()}})(), {})
    assert v.value is True and v.probs == {"true": 1.0} and v.confidence == 1.0
    print("ok")
