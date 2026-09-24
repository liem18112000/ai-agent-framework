"""InMemoryVectorStore — the canonical pure-Python VectorStore (no DB, no network).

The proof-of-swappability adapter behind the `VectorStore` port: nodes/edges/embeddings live in plain
dicts, vector ranking is brute-force cosine, lexical ranking is token-overlap over the node text, and the
two arms are fused with the SAME `rrf_fuse` the pgvector adapter uses (reused, never forked). Every method
returns the SAME SHAPE as `PgMemoryStore` (`{id,type,title}` dicts from `search`, synopsis strings from
`recall`), so it is a true drop-in — used offline and as the deterministic test fixture for the contract.
"""

from __future__ import annotations

import math

from common.memory.pg.store import rrf_fuse  # reuse the pure fusion helper — do NOT fork it
from common.memory.vector_store import DEFAULT_SCOPES

# The projected columns PgMemoryStore.upsert_node persists (mirrors its INSERT column list).
_NODE_COLS = (
    "id", "type", "kind", "title", "synopsis", "source_url", "content_uri",
    "run_id", "context_id", "scope", "status", "confidence",
)
_LESSON_KINDS = ("lesson", "correction", "gotcha")


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity in [-1, 1]; 0-norm / empty vectors → -1.0 (never ranked ahead of a real match)."""
    if not a or not b:
        return -1.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return -1.0
    return dot / (na * nb)


def _tokens(text: str) -> set[str]:
    """Lowercase alphanumeric tokens (the in-memory stand-in for `to_tsvector('simple', …)`)."""
    out, cur = set(), []
    for ch in text.lower():
        if ch.isalnum():
            cur.append(ch)
        elif cur:
            out.add("".join(cur))
            cur = []
    if cur:
        out.add("".join(cur))
    return out


class InMemoryVectorStore:
    """A VectorStore backed by plain dicts — cosine vector ranking + token-overlap lexical ranking."""

    def __init__(self) -> None:
        self._nodes: dict[str, dict] = {}          # id -> projected columns (+ merged meta)
        self._emb: dict[str, list[float]] = {}      # id -> embedding vector
        self._edges: dict[tuple[str, str], dict] = {}  # (source_id, target) -> edge
        self._created: dict[str, int] = {}          # id -> insertion seq (stands in for created_at)
        self._seq = 0

    # --- writes ---------------------------------------------------------- #

    async def upsert_node(self, node: dict) -> None:
        """INSERT … ON CONFLICT DO UPDATE — overwrite the projected columns, MERGE meta (like pg's `||`)."""
        nid = node.get("id")
        cur = self._nodes.get(nid, {})
        row = {c: node.get(c) for c in _NODE_COLS}
        row["scope"] = row["scope"] or "context"      # schema DEFAULTs for the NOT NULL columns
        row["status"] = row["status"] or "active"
        row["confidence"] = row["confidence"] or "high"
        meta = dict(cur.get("meta") or {})
        meta.update(node.get("meta") or {})           # memory_node.meta || EXCLUDED.meta
        row["meta"] = meta
        if nid not in self._created:
            self._created[nid] = self._seq
            self._seq += 1
        self._nodes[nid] = row

    async def upsert_edges(self, edges: list[dict]) -> None:
        """INSERT … ON CONFLICT (source_id,target) DO UPDATE — keyed dict mirrors the composite PK."""
        for e in edges or []:
            key = (e.get("source_id"), e.get("target"))
            self._edges[key] = {
                "source_id": e.get("source_id"), "target": e.get("target"), "type": e.get("type"),
                "origin": e.get("origin"), "in_scope": bool(e.get("in_scope")),
            }

    async def set_embedding(self, node_id: str, vec: list[float], *, emb_hash: str = "") -> None:
        """Attach the embedding vector + stamp `emb_hash` into the node's meta (as pg does in jsonb)."""
        self._emb[node_id] = list(vec)
        node = self._nodes.get(node_id)
        if node is not None:  # pg's UPDATE … WHERE id=:id is a no-op when the row is absent
            node.setdefault("meta", {})["emb_hash"] = emb_hash

    async def embedding_fresh(self, node_id: str, emb_hash: str) -> bool:
        """True iff the row has an embedding AND it was computed from this exact text (hash match)."""
        node = self._nodes.get(node_id)
        return (
            node is not None
            and self._emb.get(node_id) is not None
            and (node.get("meta") or {}).get("emb_hash") == emb_hash
        )

    async def ensure_ann_index(self) -> None:
        """No-op: brute-force cosine needs no ANN index (kept for VectorStore parity with pgvector)."""
        return

    # --- reads ----------------------------------------------------------- #

    def _passes(self, node: dict, types, scopes) -> bool:
        if node.get("status", "active") != "active" or node.get("scope", "context") not in scopes:
            return False
        return not types or node.get("type") in types

    def _vector_ids(self, q_embed, types, scopes, k) -> list[str]:
        scored = [
            (self._cosine_to(nid, q_embed), nid)
            for nid, node in self._nodes.items()
            if self._emb.get(nid) is not None and self._passes(node, types, scopes)
        ]
        scored = [s for s in scored if s[0] > 0.0]  # MEM-03: drop non-positive-similarity hits
        scored.sort(key=lambda s: (-s[0], s[1]))  # similarity desc, id asc (deterministic tie-break)
        return [nid for _, nid in scored[:k]]

    def _cosine_to(self, nid: str, q_embed) -> float:
        return _cosine(q_embed, self._emb[nid])

    def _lexical_ids(self, q_text, types, scopes, k) -> list[str]:
        q = _tokens(q_text)
        if not q:
            return []
        scored = []
        for nid, node in self._nodes.items():
            if not self._passes(node, types, scopes):
                continue
            text = f"{node.get('title') or ''} {node.get('synopsis') or ''}"  # matches the tsv source
            overlap = len(q & _tokens(text))
            if overlap:  # tsv @@ plainto_tsquery requires at least one term to match
                scored.append((overlap, nid))
        scored.sort(key=lambda s: (-s[0], s[1]))  # rank desc, id asc
        return [nid for _, nid in scored[:k]]

    def _recent(self, types, scopes, k) -> list[dict]:
        rows = [n for n in self._nodes.values() if self._passes(n, types, scopes)]
        rows.sort(key=lambda n: self._created.get(n["id"], 0), reverse=True)  # created_at DESC
        return [self._project(n) for n in rows[:k]]

    def _hydrate(self, ids: list[str]) -> list[dict]:
        return [self._project(self._nodes[i]) for i in ids if i in self._nodes]

    @staticmethod
    def _project(node: dict) -> dict:
        """The `{id,type,title}` result shape PgMemoryStore hydrates."""
        return {"id": node.get("id"), "type": node.get("type"), "title": node.get("title")}

    async def search(
        self, *, q_text: str = "", q_embed: list[float] | None = None,
        types: list[str] | None = None, scopes: list[str] | None = None, k: int = 40,
    ) -> list[dict]:
        """Hybrid recall: vector-nearest ∪ lexical, RRF-fused (empty query → most-recent), pg-shape rows."""
        scopes = scopes or list(DEFAULT_SCOPES)
        if not q_text and q_embed is None:
            return self._recent(types, scopes, k)  # MEM-03: browse only on an EMPTY query
        vec_ids = self._vector_ids(q_embed, types, scopes, k) if q_embed else []
        lex_ids = self._lexical_ids(q_text, types, scopes, k) if q_text else []
        if not vec_ids and not lex_ids:
            return []  # MEM-03: a real query that matched nothing → no false-positive recent nodes
        return self._hydrate(rrf_fuse(vec_ids, lex_ids, limit=k))

    async def grounded(self, candidate: str, anchors: set[str]) -> bool:
        """B5 gate: candidate IS an anchor or shares an edge with one."""
        if not anchors or candidate in anchors:
            return True
        for e in self._edges.values():
            if (e["source_id"] == candidate and e["target"] in anchors) or (
                e["target"] == candidate and e["source_id"] in anchors
            ):
                return True
        return False

    async def recall(
        self, *, seed_refs: set[str], q_embed: list[float] | None = None, limit: int = 10
    ) -> list[str]:
        """Prior-lesson recall: structural (edge → seed_refs) ∪ semantic (shared, vector-nearest), synopses."""
        out: list[str] = []
        seen: set[str] = set()
        if seed_refs:
            cands = [
                n for n in self._nodes.values()
                if n.get("status", "active") == "active" and n.get("kind") in _LESSON_KINDS
                and self._edges_to(n["id"], seed_refs)
            ]
            cands.sort(key=lambda n: (0 if n.get("confidence") == "high" else 1, self._created.get(n["id"], 0)))
            for n in cands:
                syn = n.get("synopsis")
                if syn and n["id"] not in seen:
                    seen.add(n["id"])
                    out.append(syn)
                    if len(out) >= limit:
                        return out[:limit]
        if q_embed and len(out) < limit:
            sem = [
                n for n in self._nodes.values()
                if n.get("status", "active") == "active"
                and n.get("scope", "context") in DEFAULT_SCOPES
                and n.get("kind") in _LESSON_KINDS and self._emb.get(n["id"]) is not None
            ]
            sem.sort(key=lambda n: (-self._cosine_to(n["id"], q_embed), n["id"]))
            for n in sem[:limit]:
                syn = n.get("synopsis")
                if syn and n["id"] not in seen:
                    seen.add(n["id"])
                    out.append(syn)
        return out[:limit]

    def _edges_to(self, source_id: str, targets: set[str]) -> bool:
        return any(
            e["source_id"] == source_id and e["target"] in targets for e in self._edges.values()
        )
