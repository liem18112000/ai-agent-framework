"""V0/V1/V2 — the provider-sourced judge factories + the opt-in semantic-rubric tier.

All offline, no network: the provider/model is either blanked (VERTEX_* = "" via the session
fixture → clean skip) or mocked. Proves (a) the whole judged surface skips cleanly offline, and
(b) when configured the judge/embeddings/judge-model come from the ONE provider, never OpenAI (I8).
"""

from __future__ import annotations

import pytest

from test_evaluation.eval import judge as J
from test_evaluation.eval import judged
from test_evaluation.metrics import ragas_judge


class _FakeProvider:
    """A configured provider whose text calls are recorded — never touches the network."""

    name = "claude"

    def __init__(self, answer="yes"):
        self.answer = answer
        self.prompts: list[str] = []

    def is_configured(self) -> bool:
        return True

    def complete(self, prompt: str, *, max_tokens: int) -> str:
        self.prompts.append(prompt)
        return self.answer


# --- V0: clean offline skip (VERTEX_* blanked by the session fixture, ragas absent) -------------

def test_judge_factories_skip_cleanly_offline():
    assert J.provider_configured() is False
    assert J.ragas_ready() is False
    assert J.judge_model_id() is None
    assert J.build_ragas_llm() is None
    assert J.build_ragas_embeddings() is None
    assert J.build_semantic_judge() is None


def test_semantic_rubric_tier_skips_offline():
    assert judged.score_semantic_rubrics("any understanding") is None
    from test_evaluation.models import EvalReport
    r = judged.attach_semantic(EvalReport(context_id="c"), "understanding")
    assert r.semantic is None


# --- V2: the semantic judge is provider-sourced (VertexClaude.complete), not OpenAI -------------

def test_semantic_judge_is_provider_sourced(monkeypatch):
    fake = _FakeProvider(answer="yes")
    monkeypatch.setattr(J, "get_provider", lambda: fake)

    judge = J.build_semantic_judge()
    assert judge is not None
    assert judge("Does it name the AC?", "The AC is X.") is True
    assert fake.prompts, "the judge must call the provider (VertexClaude), never OpenAI"

    from test_evaluation.metrics.rubrics import SEMANTIC_RUBRICS
    result = judged.score_semantic_rubrics("und", judge=judge)
    assert result is not None
    assert result.names_the_ac is True and result.declares_gaps_honestly is True
    assert len(fake.prompts) == 1 + len(SEMANTIC_RUBRICS)


def test_semantic_judge_parses_no(monkeypatch):
    monkeypatch.setattr(J, "get_provider", lambda: _FakeProvider(answer="No, it does not."))
    judge = J.build_semantic_judge()
    assert judge("q", "text") is False


# --- V0/V1: judge model + RAGAS llm/embeddings come from the provider config (I8) ---------------

def test_judge_model_id_is_provider_sourced(monkeypatch):
    monkeypatch.setenv("VERTEX_PROJECT", "proj")
    monkeypatch.setenv("VERTEX_LOCATION", "us-east5")
    monkeypatch.setenv("VERTEX_MODEL", "claude-test")
    assert J.judge_model_id() == "vertex_ai/claude-test"


def test_ragas_llm_and_embeddings_are_provider_sourced_not_openai(monkeypatch):
    monkeypatch.setenv("VERTEX_PROJECT", "proj")
    monkeypatch.setenv("VERTEX_LOCATION", "us-east5")
    monkeypatch.setenv("VERTEX_MODEL", "claude-test")
    monkeypatch.setattr(ragas_judge, "available", lambda: True)

    seen = {}

    def _wrap_llm(cfg):
        seen["llm"] = cfg
        return "LLM"

    def _wrap_emb(cfg):
        seen["emb"] = cfg
        return "EMB"

    monkeypatch.setattr(J, "_wrap_ragas_llm", _wrap_llm)
    monkeypatch.setattr(J, "_wrap_ragas_embeddings", _wrap_emb)

    assert J.build_ragas_llm() == "LLM"
    assert J.build_ragas_embeddings() == "EMB"
    # sourced from the provider's Vertex config — never RAGAS's OpenAI default
    assert seen["llm"] == ("proj", "us-east5", "claude-test")
    assert seen["emb"] == ("proj", "us-east5", "claude-test")


# --- V1: ragas_judge.judge refuses the silent OpenAI default (llm/embeddings=None) --------------

def test_ragas_judge_refuses_openai_default():
    with pytest.raises(ValueError, match="provider-sourced"):
        ragas_judge.judge("q", "understanding", ["ctx"], "ref")  # llm/embeddings default None
    with pytest.raises(ValueError, match="provider-sourced"):
        ragas_judge.judge("q", "understanding", ["ctx"], "ref", llm=object())  # embeddings None
