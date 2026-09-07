"""PgMemoryStore (M0/M1 skeleton) — the pgvector recall tier behind the MemoryBank.

Writes (upsert_node/upsert_edges/set_embedding) are driven by the async projector (M2); reads
(search/grounded/recall) back the retrieval facade (`common.memory.retrieve`). GCS stays the
source of truth — every method here is best-effort and a projection of what GCS already holds.

Embeddings are bound as a text literal cast to `vector` (`CAST(:emb AS vector)`) so no asyncpg
pgvector codec registration is needed for the first slices; M4 may switch to the registered
codec for throughput. Schema is applied idempotently on first use (lazy, like DatabaseTaskStore).
"""

from __future__ import annotations

from common.memory.pg.schema import SCHEMA_SQL
from common.monitoring import get_logger

log = get_logger("memory.pg")


def _vec_literal(vec: list[float]) -> str:
    """pgvector text form: '[0.1,0.2,...]' (bound as a param, cast to vector in SQL)."""
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


def rrf_fuse(*ranked_lists: list[str], k0: int = 60, limit: int = 40) -> list[str]:
    """Reciprocal-rank fusion of ranked id lists → ids by descending fused score (id-asc tie-break).
    Score of an id = Σ 1/(k0 + rank) over the lists it appears in (rank 1-based). Pure — the one
    piece of the hybrid path unit-tested offline; the SQL arms feed it two id lists."""
    scores: dict[str, float] = {}
    for ids in ranked_lists:
        for rank, node_id in enumerate(ids, start=1):
            scores[node_id] = scores.get(node_id, 0.0) + 1.0 / (k0 + rank)
    return sorted(scores, key=lambda i: (-scores[i], i))[:limit]


class PgMemoryStore:
    def __init__(self, engine) -> None:
        self._engine = engine
        self._ready = False

    async def _ensure(self) -> None:
        """Apply the schema once per process (idempotent CREATE … IF NOT EXISTS)."""
        if self._ready:
            return
        from sqlalchemy import text
        async with self._engine.begin() as conn:
            await conn.execute(text(SCHEMA_SQL))
        self._ready = True

    # --- writes (projector, M2) --- #
    async def upsert_node(self, node: dict) -> None:
        """INSERT … ON CONFLICT (id) DO UPDATE — a note/insight projection (no embedding here)."""
        from sqlalchemy import text
        await self._ensure()
        cols = ("id", "type", "kind", "title", "synopsis", "source_url", "content_uri",
                "run_id", "context_id", "scope", "status", "confidence", "meta")
        params = {c: node.get(c) for c in cols}
        params["meta"] = params["meta"] or {}
        sql = text(
            "INSERT INTO memory_node (id,type,kind,title,synopsis,source_url,content_uri,"
            "run_id,context_id,scope,status,confidence,meta) VALUES "
            "(:id,:type,:kind,:title,:synopsis,:source_url,:content_uri,"
            ":run_id,:context_id,:scope,:status,:confidence,CAST(:meta AS jsonb)) "
            "ON CONFLICT (id) DO UPDATE SET "
            "type=EXCLUDED.type, kind=EXCLUDED.kind, title=EXCLUDED.title, synopsis=EXCLUDED.synopsis, "
            "source_url=EXCLUDED.source_url, content_uri=EXCLUDED.content_uri, run_id=EXCLUDED.run_id, "
            "context_id=EXCLUDED.context_id, scope=EXCLUDED.scope, status=EXCLUDED.status, "
            "confidence=EXCLUDED.confidence, meta=memory_node.meta || EXCLUDED.meta"
        )  # meta MERGED (not replaced) so set_embedding's emb_hash survives a re-project
        import json
        params["meta"] = json.dumps(params["meta"])
        async with self._engine.begin() as conn:
            await conn.execute(sql, params)

    async def upsert_edges(self, edges: list[dict]) -> None:
        from sqlalchemy import text
        if not edges:
            return
        await self._ensure()
        sql = text(
            "INSERT INTO memory_edge (source_id,target,type,origin,in_scope) "
            "VALUES (:source_id,:target,:type,:origin,:in_scope) "
            "ON CONFLICT (source_id,target) DO UPDATE SET "
            "type=EXCLUDED.type, origin=EXCLUDED.origin, in_scope=EXCLUDED.in_scope"
        )
        rows = [{"source_id": e.get("source_id"), "target": e.get("target"), "type": e.get("type"),
                 "origin": e.get("origin"), "in_scope": bool(e.get("in_scope"))} for e in edges]
        async with self._engine.begin() as conn:
            await conn.execute(sql, rows)

    async def set_embedding(self, node_id: str, vec: list[float], *, emb_hash: str = "") -> None:
        from sqlalchemy import text
        await self._ensure()
        sql = text("UPDATE memory_node SET embedding = CAST(:emb AS vector), "
                   "meta = coalesce(meta, '{}'::jsonb) || jsonb_build_object('emb_hash', :h) "
                   "WHERE id = :id")
        async with self._engine.begin() as conn:
            await conn.execute(sql, {"emb": _vec_literal(vec), "h": emb_hash, "id": node_id})

    async def embedding_fresh(self, node_id: str, emb_hash: str) -> bool:
        """True if the row already has an embedding computed from this exact text (content-hash
        skip) — lets the projector avoid a redundant Vertex call on an unchanged re-project."""
        from sqlalchemy import text
        await self._ensure()
        sql = text("SELECT (embedding IS NOT NULL AND meta->>'emb_hash' = :h) "
                   "FROM memory_node WHERE id = :id")
        async with self._engine.connect() as conn:
            return bool((await conn.execute(sql, {"h": emb_hash, "id": node_id})).scalar())

    # --- reads (retrieval facade) --- #
    async def search(self, *, q_text: str = "", q_embed: list[float] | None = None,
                     types: list[str] | None = None, scopes: list[str] | None = None,
                     k: int = 40) -> list[dict]:
        """Hybrid recall (M4): vector-nearest `embedding <=> q` ∪ full-text `tsv @@ q`, RRF-fused,
        filtered to active + scope (+ optional type). Empty query → most-recent active nodes. Each
        arm is one small query; fusion is `rrf_fuse` (pure, unit-tested). Best-effort."""
        await self._ensure()
        scopes = scopes or ["context", "shared"]
        vec_ids = await self._vector_ids(q_embed, types, scopes, k) if q_embed else []
        lex_ids = await self._lexical_ids(q_text, types, scopes, k) if q_text else []
        if not vec_ids and not lex_ids:
            return await self._recent(types, scopes, k)
        return await self._hydrate(rrf_fuse(vec_ids, lex_ids, limit=k))

    @staticmethod
    def _scope_type_where(types, params) -> str:
        clauses = ["status = 'active'", "scope = ANY(:scopes)"]
        if types:
            clauses.append("type = ANY(:types)")
            params["types"] = types
        return " AND ".join(clauses)

    async def _vector_ids(self, q_embed, types, scopes, k) -> list[str]:
        from sqlalchemy import text
        params = {"scopes": scopes, "k": k, "q": _vec_literal(q_embed)}
        where = self._scope_type_where(types, params)
        sql = text(f"SELECT id FROM memory_node WHERE {where} AND embedding IS NOT NULL "
                   f"ORDER BY embedding <=> CAST(:q AS vector) LIMIT :k")
        async with self._engine.connect() as conn:
            return [r[0] for r in (await conn.execute(sql, params)).all()]

    async def _lexical_ids(self, q_text, types, scopes, k) -> list[str]:
        from sqlalchemy import text
        params = {"scopes": scopes, "k": k, "t": q_text}
        where = self._scope_type_where(types, params)
        sql = text(f"SELECT id FROM memory_node WHERE {where} AND tsv @@ plainto_tsquery('simple', :t) "
                   f"ORDER BY ts_rank(tsv, plainto_tsquery('simple', :t)) DESC LIMIT :k")
        async with self._engine.connect() as conn:
            return [r[0] for r in (await conn.execute(sql, params)).all()]

    async def _recent(self, types, scopes, k) -> list[dict]:
        from sqlalchemy import text
        params = {"scopes": scopes, "k": k}
        where = self._scope_type_where(types, params)
        sql = text(f"SELECT id, type, title FROM memory_node WHERE {where} ORDER BY created_at DESC LIMIT :k")
        async with self._engine.connect() as conn:
            return [dict(r) for r in (await conn.execute(sql, params)).mappings().all()]

    async def _hydrate(self, ids: list[str]) -> list[dict]:
        from sqlalchemy import text
        if not ids:
            return []
        sql = text("SELECT id, type, title FROM memory_node WHERE id = ANY(:ids)")
        async with self._engine.connect() as conn:
            by_id = {r["id"]: dict(r) for r in (await conn.execute(sql, {"ids": ids})).mappings().all()}
        return [by_id[i] for i in ids if i in by_id]  # preserve the fused order

    async def grounded(self, candidate: str, anchors: set[str]) -> bool:
        """B5 structural gate as SQL: candidate IS an anchor or shares an edge with one."""
        from sqlalchemy import text
        if not anchors or candidate in anchors:
            return True
        await self._ensure()
        sql = text("SELECT EXISTS (SELECT 1 FROM memory_edge WHERE "
                   "(source_id = :c AND target = ANY(:a)) OR (target = :c AND source_id = ANY(:a)))")
        async with self._engine.connect() as conn:
            return bool((await conn.execute(sql, {"c": candidate, "a": list(anchors)})).scalar())

    async def recall(self, *, seed_refs: set[str], q_embed: list[float] | None = None,
                     limit: int = 10) -> list[str]:
        """Prior-lesson recall (M4b): structural ∪ semantic, deduped, structural-first.

        1. STRUCTURAL — lessons whose `source_refs ∩ seed_refs` is non-empty (a `memory_edge` to a
           seed anchor). Always safe; human-confidence first. Mirrors the GCS structural recall.
        2. SEMANTIC — vector-nearest lessons, but ONLY `scope='shared'` (the de-bias: a `context`
           lesson never leaks cross-run; §9). Appended after the grounded ones, up to `limit`.
        Returns statements. Best-effort."""
        from sqlalchemy import text
        await self._ensure()
        out: list[str] = []
        seen: set[str] = set()
        if seed_refs:
            sql = text(
                "SELECT n.id, n.synopsis FROM memory_node n "
                "WHERE n.status='active' AND n.kind IN ('lesson','correction','gotcha') "
                "AND EXISTS (SELECT 1 FROM memory_edge e WHERE e.source_id=n.id AND e.target = ANY(:refs)) "
                "ORDER BY (n.confidence='high') DESC, n.created_at ASC LIMIT :lim"
            )
            async with self._engine.connect() as conn:
                for rid, syn in (await conn.execute(sql, {"refs": list(seed_refs), "lim": limit})).all():
                    if syn and rid not in seen:
                        seen.add(rid)
                        out.append(syn)
        if q_embed and len(out) < limit:
            sql = text(
                "SELECT id, synopsis FROM memory_node "
                "WHERE status='active' AND scope='shared' AND kind IN ('lesson','correction','gotcha') "
                "AND embedding IS NOT NULL ORDER BY embedding <=> CAST(:q AS vector) LIMIT :lim"
            )
            async with self._engine.connect() as conn:
                for rid, syn in (await conn.execute(sql, {"q": _vec_literal(q_embed), "lim": limit})).all():
                    if syn and rid not in seen:
                        seen.add(rid)
                        out.append(syn)
        return out[:limit]
