"""LayaProvider — maps the laya sidecar's answers shape onto typed Verdicts (choice/score/noul)."""

from __future__ import annotations

import httpx

from common.adk.providers.laya import LayaProvider


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


def _patch(monkeypatch, answers):
    monkeypatch.setenv("LAYA_URL", "http://laya:9000")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp({"answers": {"q": answers}}))
    return LayaProvider()


def test_choice(monkeypatch):
    p = _patch(monkeypatch, {"choice": "billing", "confidence": 0.94,
                             "probabilities": {"billing": 0.94, "tech": 0.06}})
    v = p.choice("state", ["billing", "tech"], "which team")
    assert v.value == "billing" and v.confidence == 0.94 and v.probs["billing"] == 0.94


def test_score_normalised(monkeypatch):
    # ordinal 1.84 over levels of span 2 -> 0.92
    p = _patch(monkeypatch, {"score": 1.84, "confidence": 0.8})
    v = p.score("state", "how urgent", ["low", "med", "high"])
    assert abs(v.value - 0.92) < 1e-9 and v.confidence == 0.8


def test_noul_confidence_derived(monkeypatch):
    # no confidence in payload -> derived |p-0.5|*2
    p = _patch(monkeypatch, {"noul": 0.2})
    v = p.noul("state", "will they churn")
    assert v.value is False and v.probs == {"true": 0.2} and abs(v.confidence - 0.6) < 1e-9


def test_is_configured(monkeypatch):
    monkeypatch.delenv("LAYA_URL", raising=False)
    assert LayaProvider().is_configured() is False
    monkeypatch.setenv("LAYA_URL", "http://x")
    assert LayaProvider().is_configured() is True
