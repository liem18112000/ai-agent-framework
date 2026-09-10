"""VertexEmbedder — the Vertex AI text-embedding adapter for the Embedder port.

`vertexai` is imported lazily, inside the model accessor and the write path, so importing the
port/package never requires the Vertex client library (offline/test runs stay free of it).
"""

from __future__ import annotations

import asyncio
import os

from common.embed.embedder import TASK_DOCUMENT, TASK_QUERY
from common.monitoring import get_logger

log = get_logger("memory.embed")


class VertexEmbedder:
    """An `Embedder` backed by a Vertex `TextEmbeddingModel`, built lazily on first embed."""

    def __init__(self, model_name: str, location: str, dims: int) -> None:
        self._model_name = model_name
        self._location = location
        self._dims = dims
        self._model = None

    @classmethod
    def from_env(cls) -> VertexEmbedder:
        """Build from the same env the module read: MEMORY_EMBED_MODEL / _LOCATION / _DIMS."""
        return cls(
            model_name=os.environ.get("MEMORY_EMBED_MODEL", "text-multilingual-embedding-002"),
            location=os.environ.get("MEMORY_EMBED_LOCATION", "us-central1"),
            dims=int(os.environ.get("MEMORY_EMBED_DIMS", "768")),
        )

    @property
    def dims(self) -> int:
        return self._dims

    def is_configured(self) -> bool:
        """True when the Vertex project needed to embed is present (location has a regional default)."""
        return bool(os.environ.get("VERTEX_PROJECT"))

    def _get_model(self):
        if self._model is None:
            import vertexai
            from vertexai.language_models import TextEmbeddingModel

            vertexai.init(project=os.environ["VERTEX_PROJECT"], location=self._location)
            self._model = TextEmbeddingModel.from_pretrained(self._model_name)
        return self._model

    def embed_texts(self, texts: list[str], *, task: str = TASK_DOCUMENT) -> list[list[float]]:
        """Embed a batch (blocking). Called only via the async wrappers, off the event loop."""
        from vertexai.language_models import TextEmbeddingInput

        return [e.values for e in
                self._get_model().get_embeddings([TextEmbeddingInput(t, task) for t in texts])]

    async def aembed_one(self, text: str, *, task: str = TASK_DOCUMENT) -> list[float]:
        """One embedding, thread-offloaded; empty text or failure → []."""
        if not text:
            return []
        try:
            vecs = await asyncio.to_thread(self.embed_texts, [text], task=task)
            return vecs[0] if vecs else []
        except Exception as exc:  # noqa: BLE001 — embedding is best-effort; row lands without a vector
            log.warning("memory: embed failed (%s); leaving embedding NULL", exc)
            return []

    async def aembed_batch(self, texts: list[str], *, task: str = TASK_DOCUMENT) -> list[list[float]]:
        """Embed a whole batch in ONE Vertex call, thread-offloaded; best-effort → [] on failure."""
        if not texts:
            return []
        try:
            return await asyncio.to_thread(self.embed_texts, texts, task=task)
        except Exception as exc:  # noqa: BLE001 — batch embedding is best-effort
            log.warning("memory: batch embed of %d text(s) failed (%s); left NULL", len(texts), exc)
            return []

    async def aembed_query(self, text: str) -> list[float]:
        """Embed a search query (RETRIEVAL_QUERY). Used by the hybrid read path (M4)."""
        return await self.aembed_one(text, task=TASK_QUERY)
