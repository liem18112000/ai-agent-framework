"""VectorStore port — the semantic-recall contract the MemoryBank duck-types (pgvector today, swappable).

Importing this module pulls in nothing but stdlib, so the port is safe to reference from anywhere
(offline/test runs never touch pgvector/SQLAlchemy — that lives behind the `pgvector` adapter, and the
pure-Python `InMemoryVectorStore` proves the contract is backend-agnostic).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class VectorStore(Protocol):
    """Semantic + structural recall over memory nodes/edges — the domain contract every backend implements.

    `search` is hybrid (vector-nearest ∪ lexical, RRF-fused); `recall` is structural(edge) ∪ semantic(vector);
    `grounded` is the B5 structural gate. Results are the SAME SHAPE across adapters: `{id,type,title}` dicts
    from `search`, synopsis strings from `recall`, so any adapter is a true drop-in for another.
    """

    async def upsert_node(self, node: dict) -> None:
        """Insert-or-update a node projection (id/type/kind/title/synopsis/scope/… — no embedding here)."""
        ...

    async def upsert_edges(self, edges: list[dict]) -> None:
        """Insert-or-update directed edges (`{source_id,target,type,origin,in_scope}`)."""
        ...

    async def set_embedding(self, node_id: str, vec: list[float], *, emb_hash: str = "") -> None:
        """Attach an embedding vector (+ its content hash) to an existing node."""
        ...

    async def embedding_fresh(self, node_id: str, emb_hash: str) -> bool:
        """True if the node already has an embedding computed from this exact text (content-hash match)."""
        ...

    async def ensure_ann_index(self) -> None:
        """Build the ANN index backing vector search (idempotent; may be a no-op for brute-force backends)."""
        ...

    async def search(
        self,
        *,
        q_text: str = "",
        q_embed: list[float] | None = None,
        types: list[str] | None = None,
        scopes: list[str] | None = None,
        k: int = 40,
    ) -> list[dict]:
        """Hybrid recall: vector-nearest ∪ lexical, RRF-fused → `{id,type,title}` dicts (scope/type filtered)."""
        ...

    async def recall(
        self, *, seed_refs: set[str], q_embed: list[float] | None = None, limit: int = 10
    ) -> list[str]:
        """Prior-lesson recall: structural (edge ∩ `seed_refs`) ∪ semantic (vector-nearest), synopsis strings."""
        ...

    async def grounded(self, candidate: str, anchors: set[str]) -> bool:
        """B5 structural gate: `candidate` IS an anchor or shares an edge with one."""
        ...
