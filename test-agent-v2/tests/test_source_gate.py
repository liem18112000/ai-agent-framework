"""G3 source-activation gate — the JEV `noul` cascade reused as a source selector (default OFF)."""

from __future__ import annotations

from common.adk.providers.decision import Verdict
from knowledge_gathering.gather.explore import source_gate as sg


class _Prov:
    """A DecisionProvider double returning one fixed Verdict for every `noul`."""

    name = "fake"

    def __init__(self, verdict: Verdict):
        self._v = verdict

    def is_configured(self) -> bool:
        return True

    def noul(self, state: str, statement: str) -> Verdict:
        return self._v


def _cascade(verdict, keys=("atlassian_search",), conf_min=0.4, tau=0.5):
    return sg.apply_cascade(keys, state="s", provider=_Prov(verdict), conf_min=conf_min, tau=tau)


def test_confident_below_bar_is_the_only_skip():
    # confident (0.7 ≥ 0.4) AND below the run bar (P=0.2 < 0.5) → the one case that drops a source.
    assert _cascade(Verdict(value=False, probs={"true": 0.2, "false": 0.8}, confidence=0.7)) == set()


def test_confident_above_bar_fires():
    assert _cascade(Verdict(value=True, probs={"true": 0.9}, confidence=0.8)) == {"atlassian_search"}


def test_low_confidence_never_skips():
    # below the bar (P=0.1) but UNSURE (conf 0.2 < 0.4) → fire; never trust a low-confidence skip.
    assert _cascade(Verdict(value=False, probs={"true": 0.1}, confidence=0.2)) == {"atlassian_search"}


def test_p_true_falls_back_to_boolean_when_no_probs():
    # no distribution → P = 1.0 for a True value → above bar → fire.
    assert _cascade(Verdict(value=True, probs=None, confidence=0.9)) == {"atlassian_search"}


def test_gate_error_fires_never_drops():
    class _Boom:
        name = "boom"

        def is_configured(self):
            return True

        def noul(self, s, t):
            raise RuntimeError("jev down")

    assert sg.apply_cascade({"x"}, state="s", provider=_Boom(), conf_min=0.4, tau=0.5) == {"x"}


def test_select_sources_noop_when_gate_off(monkeypatch):
    monkeypatch.delenv("KGA_SOURCE_GATE", raising=False)
    assert sg.select_sources({"a", "b"}, state="s") == {"a", "b"}


def test_select_sources_fires_all_when_no_backend(monkeypatch):
    # gate ON but no decision backend configured → still a no-op (worst case = today).
    monkeypatch.setenv("KGA_SOURCE_GATE", "1")
    monkeypatch.setattr(sg, "get_decision_provider", lambda: None)
    assert sg.select_sources({"a", "b"}, state="s") == {"a", "b"}
