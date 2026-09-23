"""OllamaEmbedder — a local text-embedding adapter for the Embedder port (no GCP).

Talks to Ollama's batch embeddings endpoint (`POST {OLLAMA_URL}/api/embed`, {model, input:[...]}) so the
pgvector hybrid recall tier works fully locally. Default model `nomic-embed-text` (768-dim, matching the
default `vector(768)` column). `httpx` is already a dep. Task types are ignored (nomic needs no prefix).
"""

from __future__ import annotations

import asyncio
import os

from common.embed.embedder import TASK_DOCUMENT
from common.monitoring import get_logger

log = get_logger("memory.embed")


class OllamaEmbedder:
    """An `Embedder` backed by a local Ollama server."""

    def __init__(self, model: str, url: str, dims: int) -> None:
        self._model, self._url, self._dims = model, url.rstrip("/"), dims

    @classmethod
    def from_env(cls) -> OllamaEmbedder:
        return cls(
            model=os.environ.get("MEMORY_EMBED_MODEL", "nomic-embed-text"),
            url=os.environ.get("OLLAMA_URL", "http://ollama:11434"),
            dims=int(os.environ.get("MEMORY_EMBED_DIMS", "768")),
        )

    @property
    def dims(self) -> int:
        return self._dims

    def is_configured(self) -> bool:
        return bool(self._url and self._model)

    def embed_texts(self, texts: list[str], *, task: str = TASK_DOCUMENT) -> list[list[float]]:
        """Embed a batch in one call (blocking; called off the event loop)."""
        import httpx

        r = httpx.post(f"{self._url}/api/embed", json={"model": self._model, "input": texts},
                       timeout=float(os.environ.get("OLLAMA_EMBED_TIMEOUT", "120")))
        r.raise_for_status()
        return r.json()["embeddings"]

    async def aembed_batch(self, texts: list[str], *, task: str = TASK_DOCUMENT) -> list[list[float]]:
        if not texts:
            return []
        try:
            return await asyncio.to_thread(self.embed_texts, texts, task=task)
        except Exception as exc:  # noqa: BLE001 — best-effort; rows land without a vector
            log.warning("memory: ollama batch embed of %d text(s) failed (%s); left NULL", len(texts), exc)
            return []

    async def aembed_query(self, text: str) -> list[float]:
        if not text:
            return []
        vecs = await self.aembed_batch([text])
        return vecs[0] if vecs else []
