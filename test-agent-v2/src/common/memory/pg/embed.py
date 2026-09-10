"""Vertex text embeddings for the recall tier (M3).

Thin facade over the ports-and-adapters Embedder (`common.embed`): the public functions below
delegate to a lazily-built, cached embedder, so every existing call site keeps working while
`vertexai` no longer lives at this module's top — it stays behind the selected adapter, imported
lazily on first embed.
"""

from __future__ import annotations

from common.embed import TASK_DOCUMENT, Embedder, select_embedder

_embedder: Embedder | None = None


def _get_embedder() -> Embedder:
    """The selected embedder, built once and cached (mirrors the old module-level model cache)."""
    global _embedder
    if _embedder is None:
        _embedder = select_embedder()
    return _embedder


def embed_configured() -> bool:
    """True when the Vertex project needed to embed is present (location has a regional default)."""
    return _get_embedder().is_configured()


def embed_texts(texts: list[str], *, task: str = TASK_DOCUMENT) -> list[list[float]]:
    """Embed a batch (blocking). Called only via `aembed_one` off the event loop."""
    return _get_embedder().embed_texts(texts, task=task)


async def aembed_one(text: str, *, task: str = TASK_DOCUMENT) -> list[float]:
    """One embedding, thread-offloaded; empty text or failure → []."""
    return await _get_embedder().aembed_one(text, task=task)


async def aembed_batch(texts: list[str], *, task: str = TASK_DOCUMENT) -> list[list[float]]:
    """Embed a whole batch in ONE Vertex call, thread-offloaded; best-effort → [] on failure."""
    return await _get_embedder().aembed_batch(texts, task=task)


async def aembed_query(text: str) -> list[float]:
    """Embed a search query (RETRIEVAL_QUERY). Used by the hybrid read path (M4)."""
    return await _get_embedder().aembed_query(text)


def build_embedder():
    """The DOCUMENT batch embedder for the projector drain, or None when Vertex isn't configured."""
    if not embed_configured():
        return None

    async def _embed(texts: list[str]) -> list[list[float]]:
        return await aembed_batch(texts, task=TASK_DOCUMENT)

    return _embed
