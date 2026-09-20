"""Ports-and-adapters Embedder — a swappable text-embedding provider (Vertex today)."""

from common.embed.embedder import TASK_DOCUMENT, TASK_QUERY, Embedder
from common.embed.vertex import VertexEmbedder

__all__ = [
    "TASK_DOCUMENT",
    "TASK_QUERY",
    "Embedder",
    "VertexEmbedder",
]
