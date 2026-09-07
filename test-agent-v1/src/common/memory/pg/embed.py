"""Vertex text embeddings for the recall tier (M3).

Multilingual by default (`text-multilingual-embedding-002`, 768d) so a German dunning page and an
English test note land near each other. Runs ONLY in the projector drain, thread-offloaded and
bounded — never in a request handler (Cloud Run throttles CPU after the response, and serial Vertex
calls have already tripped ERROR_TIMEOUT here). `vertexai` is imported lazily so importing this
module (and stubbing the embedder in tests) needs no google-cloud-aiplatform install.

Embeddings are asymmetric: documents embed with RETRIEVAL_DOCUMENT, queries with RETRIEVAL_QUERY —
this measurably lifts recall over using one task type for both.
"""

from __future__ import annotations

import asyncio
import os

from common.monitoring import get_logger

log = get_logger("memory.embed")

_MODEL_NAME = os.environ.get("MEMORY_EMBED_MODEL", "text-multilingual-embedding-002")
# Embeddings need a REGIONAL Vertex endpoint: the vertexai SDK 404s on location="global" for
# embedding models (the Claude/AnthropicVertex path uses global, but that's a different SDK). So this
# is deliberately separate from VERTEX_LOCATION. Default us-central1 (broad); override per deploy.
_EMBED_LOCATION = os.environ.get("MEMORY_EMBED_LOCATION", "us-central1")
TASK_DOCUMENT = "RETRIEVAL_DOCUMENT"
TASK_QUERY = "RETRIEVAL_QUERY"

_model = None  # cached across calls (vertexai.init + from_pretrained are not free)


def embed_configured() -> bool:
    """True when the Vertex project needed to embed is present (location has a regional default)."""
    return bool(os.environ.get("VERTEX_PROJECT"))


def _get_model():
    global _model
    if _model is None:
        import vertexai
        from vertexai.language_models import TextEmbeddingModel

        vertexai.init(project=os.environ["VERTEX_PROJECT"], location=_EMBED_LOCATION)
        _model = TextEmbeddingModel.from_pretrained(_MODEL_NAME)
    return _model


def embed_texts(texts: list[str], *, task: str = TASK_DOCUMENT) -> list[list[float]]:
    """Embed a batch (blocking). Called only via `aembed_one` off the event loop."""
    from vertexai.language_models import TextEmbeddingInput

    inputs = [TextEmbeddingInput(t, task) for t in texts]
    return [e.values for e in _get_model().get_embeddings(inputs)]


async def aembed_one(text: str, *, task: str = TASK_DOCUMENT) -> list[float]:
    """One embedding, thread-offloaded. Empty text → []. Best-effort — [] on failure so the
    projector still writes the metadata row (embedding stays NULL, retried on the next write)."""
    if not text:
        return []
    try:
        vecs = await asyncio.to_thread(embed_texts, [text], task=task)
        return vecs[0] if vecs else []
    except Exception as exc:  # noqa: BLE001 — embedding is best-effort; row lands without a vector
        log.warning("memory: embed failed (%s); leaving embedding NULL", exc)
        return []


async def aembed_batch(texts: list[str], *, task: str = TASK_DOCUMENT) -> list[list[float]]:
    """Embed a whole batch in ONE Vertex call, thread-offloaded. Whole-batch best-effort: any
    failure → [] (the projector re-queues those nodes), so one bad batch never breaks the drain."""
    if not texts:
        return []
    try:
        return await asyncio.to_thread(embed_texts, texts, task=task)
    except Exception as exc:  # noqa: BLE001 — batch embedding is best-effort
        log.warning("memory: batch embed of %d text(s) failed (%s); left NULL", len(texts), exc)
        return []


def build_embedder():
    """The DOCUMENT batch embedder for the projector drain, or None when Vertex isn't configured
    (→ the drain projects metadata only). Signature: async (list[str]) -> list[list[float]] — one
    Vertex call per batch (the drain groups nodes; MEMORY_EMBED_BATCH sizes the group)."""
    if not embed_configured():
        return None

    async def _embed(texts: list[str]) -> list[list[float]]:
        return await aembed_batch(texts, task=TASK_DOCUMENT)

    return _embed


async def aembed_query(text: str) -> list[float]:
    """Embed a search query (RETRIEVAL_QUERY). Used by the hybrid read path (M4)."""
    return await aembed_one(text, task=TASK_QUERY)
