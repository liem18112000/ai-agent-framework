"""TESTAGENT_TURBO profile: flips the three aggressive gates (assured iters, per-round critique,
refine passes) to faster defaults, while an explicit per-flag env still overrides."""

from __future__ import annotations

from common.adk.config import turbo_on
from common.interrogate.critique import critique_enabled
from common.interrogate.loop import _resolve_max_rounds


def test_turbo_off_is_the_quality_default(monkeypatch):
    monkeypatch.delenv("TESTAGENT_TURBO", raising=False)
    monkeypatch.delenv("INTERROGATION_CRITIQUE", raising=False)
    assert turbo_on() is False
    assert critique_enabled() is True        # B2: critique on by default
    assert _resolve_max_rounds() == 4        # B3: full re-seed passes


def test_turbo_on_flips_the_gates(monkeypatch):
    monkeypatch.setenv("TESTAGENT_TURBO", "1")
    monkeypatch.delenv("INTERROGATION_CRITIQUE", raising=False)
    assert turbo_on() is True
    assert critique_enabled() is False       # B2: critique dropped
    assert _resolve_max_rounds() == 1        # B3: one pass


def test_explicit_env_overrides_turbo(monkeypatch):
    monkeypatch.setenv("TESTAGENT_TURBO", "on")
    monkeypatch.setenv("INTERROGATION_CRITIQUE", "1")  # force it back on despite turbo
    assert critique_enabled() is True
