"""`select_embedder()` — select the Embedder backend from env (EMBED_BACKEND)."""

from __future__ import annotations

import os

from common.embed.embedder import Embedder


def select_embedder() -> Embedder:
    """Select by EMBED_BACKEND: `vertex` (default). Add new providers as extra branches."""
    backend = os.environ.get("EMBED_BACKEND", "vertex").lower()
    if backend == "vertex":
        from common.embed.vertex import VertexEmbedder

        return VertexEmbedder.from_env()
    raise ValueError(f"unknown EMBED_BACKEND: {backend!r}")
