"""Provider-sourced judge / embeddings for the OPT-IN judged eval tier (V0 / D17, I8).

NOTHING here is imported on the live scoring path: `evaluate_pack` / `evaluate_plan` and every
`metrics/*` scorer stay deterministic and LLM-free (the product property). This module is reached
only from the offline judged tier (the `eval:`-label tests and `eval/judged.py`'s opt-in helpers).

Every factory returns ``None`` — a clean skip — when the ``eval`` extra (RAGAS) is absent OR the
model provider is unconfigured (no ``VERTEX_*`` creds), so the offline suite touches no network.
When configured, the judge / embeddings / judge-model come from the ONE configured
``ModelProvider`` (``agent_model()`` / ``VertexClaudeProvider``), never RAGAS's OpenAI default (I8).
"""

from __future__ import annotations

from common.adk.model import agent_model
from common.adk.providers import get_provider
from common.env import env_float
from common.llm.vertex import vertex_config
from common.monitoring import get_logger
from test_evaluation.metrics import ragas_judge

log = get_logger("eval.judge")


def provider_configured() -> bool:
    """True when the model provider's transport is configured (``VERTEX_*`` set) — the judged
    tier's model gate, the sibling of ``eval/runner.py::creds_available``."""
    return get_provider().is_configured()


def ragas_ready() -> bool:
    """The RAGAS judged path is live only with BOTH the ``eval`` extra AND provider creds."""
    return ragas_judge.available() and provider_configured()


def judge_model_id() -> str | None:
    """The provider's model id for ADK's LLM-as-a-judge (``JudgeModelOptions.judge_model``), or
    ``None`` when unconfigured. Provider-sourced (I8) — never an OpenAI or other-vendor default."""
    model = agent_model()
    return getattr(model, "model", None) if model is not None else None


def build_ragas_llm():
    """A RAGAS LLM wrapping the provider's Claude-on-Vertex, or ``None`` when the ``eval`` extra /
    creds are absent (kills RAGAS's silent OpenAI default — V1)."""
    if not ragas_ready():
        return None
    return _wrap_ragas_llm(vertex_config())


def build_ragas_embeddings():
    """RAGAS embeddings sourced from the provider's Vertex config, or ``None`` when absent (kills
    the OpenAI embeddings default for answer-relevancy — V1)."""
    if not ragas_ready():
        return None
    return _wrap_ragas_embeddings(vertex_config())


def _noul_threshold() -> float:
    """Accept cut for the JEV noul judge: P(true) ≥ τ ⇒ True. Env ``TEV_NOUL_THRESHOLD`` (default 0.5);
    a malformed value falls back to 0.5 rather than crashing the judge."""
    import contextlib

    with contextlib.suppress(ValueError):
        return env_float("TEV_NOUL_THRESHOLD", 0.5)
    return 0.5


def build_semantic_judge():
    """A ``judge(question, text) -> bool`` backed by the provider's Claude-on-Vertex, or ``None``
    when unconfigured. Consumed by ``metrics.rubrics.judge_semantic`` in the judged tier ONLY —
    never by ``evaluate_pack`` (V2)."""
    from common.adk.providers import get_decision_provider

    llm_judge = _llm_semantic_judge()  # the fallback for the JEV path too (None when no provider creds)

    # JEV cascade (rollout step 1): a configured decision backend serves the yes/no as a typed Noul,
    # fronting the LLM. Default OFF (TPD_DECISION_BACKEND unset) → None → the LLM path (llm_judge) alone.
    decision = get_decision_provider()
    if decision is not None and decision.is_configured():
        threshold = _noul_threshold()

        def judge(question: str, text: str) -> bool:
            try:
                verdict = decision.noul(state=text, statement=question)
            except Exception as exc:  # a JEV outage falls back to the LLM judge, never crashes scoring
                if llm_judge is None:
                    raise
                log.warning("semantic judge: JEV noul failed (%s); falling back to the LLM judge", exc)
                return llm_judge(question, text)
            # Accept at P(true) >= threshold (env TEV_NOUL_THRESHOLD, default 0.5). probs is authoritative
            # when present; else fall back to the bool value. confidence is advisory here — a bool sink
            # can't carry it (see the assured cascade).
            probs = verdict.probs or {}
            p_true = probs.get("true", probs.get("yes", float(bool(verdict.value))))
            return p_true >= threshold
        return judge

    return llm_judge


def _llm_semantic_judge():
    """The Claude-on-Vertex yes/no judge closure, or ``None`` when the provider is unconfigured."""
    if not provider_configured():
        return None
    provider = get_provider()

    def judge(question: str, text: str) -> bool:
        prompt = (
            "You are a strict test-plan QA judge. Answer the QUESTION about the TEXT below with "
            "exactly 'yes' or 'no'.\n\n"
            f"QUESTION: {question}\n\nTEXT:\n{text}\n\nAnswer (yes/no):"
        )
        answer = provider.complete(prompt, max_tokens=8)
        return answer.strip().lower().startswith("y")

    return judge


def _wrap_ragas_llm(cfg):
    """Wrap Claude-on-Vertex as a RAGAS LLM. A monkeypatchable seam reached only with creds + the
    ``eval`` extra (never offline)."""
    project, location, model = cfg
    from langchain_community.chat_models import ChatLiteLLM
    from ragas.llms import LangchainLLMWrapper

    chat = ChatLiteLLM(model=f"vertex_ai/{model}", vertex_project=project, vertex_location=location)
    return LangchainLLMWrapper(chat)


def _wrap_ragas_embeddings(cfg):
    """Wrap Vertex embeddings as a RAGAS embeddings. A monkeypatchable seam reached only with
    creds + the ``eval`` extra (never offline)."""
    import os

    project, location, _model = cfg
    from langchain_google_vertexai import VertexAIEmbeddings
    from ragas.embeddings import LangchainEmbeddingsWrapper

    emb_model = os.environ.get("TEV_JUDGE_EMBED_MODEL", "text-multilingual-embedding-002")
    return LangchainEmbeddingsWrapper(
        VertexAIEmbeddings(model_name=emb_model, project=project, location=location)
    )
