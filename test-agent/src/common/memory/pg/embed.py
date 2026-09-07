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
TASK_DOCUMENT = "RETRIEVAL_DOCUMENT"
TASK_QUERY = "RETRIEVAL_QUERY"

_model = None  # cached across calls (vertexai.init + from_pretrained are not free)


def embed_configured() -> bool:
    """True when the Vertex project/location env needed to embed is present."""
    return bool(os.environ.get("VERTEX_PROJECT") and os.environ.get("VERTEX_LOCATION"))


def _get_model():
    global _model
    if _model is None:
        import vertexai
        from vertexai.language_models import TextEmbeddingModel

        vertexai.init(project=os.environ["VERTEX_PROJECT"], location=os.environ["VERTEX_LOCATION"])
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


def build_embedder():
    """The document embedder used by the projector drain, or None when Vertex isn't configured
    (→ the drain projects metadata only, i.e. M2 behaviour). Signature: async (text) -> vector."""
    if not embed_configured():
        return None

    async def _embed(text: str) -> list[float]:
        return await aembed_one(text, task=TASK_DOCUMENT)

    return _embed


async def aembed_query(text: str) -> list[float]:
    """Embed a search query (RETRIEVAL_QUERY). Used by the hybrid read path (M4)."""
    return await aembed_one(text, task=TASK_QUERY)
