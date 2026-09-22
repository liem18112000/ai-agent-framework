"""Embedder port — the text-embedding contract the recall tier duck-types (Vertex today, swappable).

Importing this module pulls in nothing but stdlib, so the port is safe to reference from anywhere
(offline/test runs never touch `vertexai` — that lives behind the `vertex` adapter).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

# Vertex `TextEmbeddingInput` task types — DOCUMENT for the stored corpus, QUERY for search text.
TASK_DOCUMENT = "RETRIEVAL_DOCUMENT"
TASK_QUERY = "RETRIEVAL_QUERY"


@runtime_checkable
class Embedder(Protocol):
    """Turns text into vectors. The batch/`embed_texts` methods embed DOCUMENTs (the stored corpus);
    `aembed_query` embeds a search string. Adapters may accept an extra `task=` kwarg, but the
    contract every caller relies on is DOCUMENT-by-default here and QUERY via `aembed_query`.
    """

    @property
    def dims(self) -> int:
        """Vector dimensionality this embedder produces (matches the `vector(N)` embedding column)."""
        ...

    def is_configured(self) -> bool:
        """True when the backing provider has the credentials/project it needs to embed."""
        ...

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch as DOCUMENTs (blocking). Called off the event loop."""
        ...

    async def aembed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of DOCUMENTs in one call, thread-offloaded; best-effort → [] on failure."""
        ...

    async def aembed_query(self, text: str) -> list[float]:
        """Embed one search query (RETRIEVAL_QUERY), thread-offloaded; best-effort → [] on failure."""
        ...
