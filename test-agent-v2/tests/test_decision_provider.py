"""DecisionProvider port + JEV cascade (rollout steps 1-2) — all offline, default OFF unchanged.

The decision backend is injected as a `FakeDecisionProvider` (canned typed Verdicts) via monkeypatch;
nothing here touches the JEV network or Vertex. Covers the registry gate, the typed-Verdict contract,
the TEV `build_semantic_judge` noul path, and the assured-loop cascade (accept-fast vs LLM fallback).
"""

from __future__ import annotations

from common.adk.providers import Verdict, get_decision_provider
from common.adk.providers.jev import JevProvider
from common.memory import MemoryBank
from common.testplan.models import CONFIRMED
from test_plan_definition.define import define
from test_plan_definition.implement import implement_plan
from tests.conftest import FakeDecisionProvider
from tests.tpd_fakes import full_fake_model

# --- registry ---------------------------------------------------------------------------------

def test_registry_off_by_default(monkeypatch):
    monkeypatch.delenv("TPD_DECISION_BACKEND", raising=False)
    assert get_decision_provider() is None


def test_registry_returns_jev_when_set(monkeypatch):
    monkeypatch.setenv("TPD_DECISION_BACKEND", "jev")
    assert isinstance(get_decision_provider(), JevProvider)


def test_registry_unknown_backend_is_off(monkeypatch):
    monkeypatch.setenv("TPD_DECISION_BACKEND", "bogus")
    assert get_decision_provider() is None


# --- fake provider returns typed Verdicts -----------------------------------------------------

def test_fake_provider_returns_typed_verdicts():
    p = FakeDecisionProvider()
    assert p.is_configured()
    for v in (p.noul("s", "q"), p.score("s", "i", ["low", "high"]), p.choice("s", ["a", "b"], "i")):
        assert isinstance(v, Verdict)


# --- call site #1: TEV build_semantic_judge -> noul -------------------------------------------

def test_semantic_judge_uses_noul_when_decision_configured(monkeypatch):
    from test_evaluation.eval import judge as judge_mod

    fake = FakeDecisionProvider(noul=Verdict(value=True, probs={"true": 0.8}, confidence=0.9))
    monkeypatch.setattr("common.adk.providers.get_decision_provider", lambda: fake)
    judge = judge_mod.build_semantic_judge()
    assert judge is not None
    assert judge("Is X covered?", "X is covered") is True  # P(true)=0.8 >= 0.5


def test_semantic_judge_noul_rejects_below_half(monkeypatch):
    from test_evaluation.eval import judge as judge_mod

    fake = FakeDecisionProvider(noul=Verdict(value=False, probs={"true": 0.2}, confidence=0.9))
    monkeypatch.setattr("common.adk.providers.get_decision_provider", lambda: fake)
    assert judge_mod.build_semantic_judge()("Is X covered?", "nope") is False


def test_semantic_judge_noul_threshold_is_configurable(monkeypatch):
    from test_evaluation.eval import judge as judge_mod

    fake = FakeDecisionProvider(noul=Verdict(value=False, probs={"true": 0.6}, confidence=0.9))
    monkeypatch.setattr("common.adk.providers.get_decision_provider", lambda: fake)
    monkeypatch.setenv("TEV_NOUL_THRESHOLD", "0.7")  # 0.6 < 0.7 → reject
    assert judge_mod.build_semantic_judge()("Is X covered?", "maybe") is False
    monkeypatch.setenv("TEV_NOUL_THRESHOLD", "0.5")  # 0.6 ≥ 0.5 → accept (also the default)
    assert judge_mod.build_semantic_judge()("Is X covered?", "maybe") is True


# --- call site #2: the assured cascade --------------------------------------------------------

async def _confirmed(bank):
    result = await define(bank, "run-6f2a", seed="LUZ-158390")
    assert result.plan.status == CONFIRMED
    return result.plan


async def test_assured_high_confidence_skips_llm_judge(pack_bucket, monkeypatch):
    """A confident, above-bar JEV Score accepts round 1 and the LLM judge_once is NEVER called."""
    monkeypatch.delenv("TPD_LLM_DETAIL", raising=False)
    fake_decision = FakeDecisionProvider(score=Verdict(value=0.92, probs=None, confidence=0.9))
    monkeypatch.setattr("common.adk.providers.get_decision_provider", lambda: fake_decision)
    bank = MemoryBank(pack_bucket)
    await _confirmed(bank)
    fake = full_fake_model()

    res = await implement_plan(bank, "run-6f2a", model=fake)
    assert res.quality is not None and res.quality.accepted and res.quality.rounds == 1
    assert abs(res.quality.final_score - 0.92) < 1e-6
    assert fake.judge_calls == 0  # LLM judge skipped — the latency/cost win
    assert res.scenarios


async def test_assured_low_confidence_falls_back_to_llm_judge(pack_bucket, monkeypatch):
    """Low JEV confidence → the gate returns None → the existing LLM judge runs unchanged."""
    monkeypatch.delenv("TPD_LLM_DETAIL", raising=False)
    fake_decision = FakeDecisionProvider(score=Verdict(value=0.92, probs=None, confidence=0.5))
    monkeypatch.setattr("common.adk.providers.get_decision_provider", lambda: fake_decision)
    bank = MemoryBank(pack_bucket)
    await _confirmed(bank)
    fake = full_fake_model()  # LLM judge = 0.9 → accepts once it runs

    res = await implement_plan(bank, "run-6f2a", model=fake)
    assert res.quality is not None and res.quality.accepted
    assert fake.judge_calls == 1  # fell back to the LLM judge


async def test_assured_default_off_uses_llm_judge(pack_bucket, monkeypatch):
    """Backend unset (default) → gate is a no-op → the LLM judge runs exactly as today."""
    monkeypatch.delenv("TPD_LLM_DETAIL", raising=False)
    monkeypatch.delenv("TPD_DECISION_BACKEND", raising=False)
    bank = MemoryBank(pack_bucket)
    await _confirmed(bank)
    fake = full_fake_model()

    res = await implement_plan(bank, "run-6f2a", model=fake)
    assert res.quality is not None and res.quality.accepted
    assert fake.judge_calls == 1  # unchanged LLM path
