"""Confluence read-only endpoints (mixin over BaseClient)."""

from __future__ import annotations


class ConfluenceMixin:
    async def get_page(self, page_id: str) -> dict:
        return await self._get(f"/wiki/api/v2/pages/{page_id}", {"body-format": "storage"})

    async def search_cql(self, cql: str, *, limit: int = 10) -> list[str]:
        """Content/page IDs matching `cql` (first page only, capped at limit).

        Uses the classic search endpoint ``/wiki/rest/api/search`` — the v2 page API this
        client otherwise uses has no CQL search. Each result nests its id under `content`.
        """
        data = await self._get("/wiki/rest/api/search", {"cql": cql, "limit": limit})
        results = data.get("results", []) if isinstance(data, dict) else []
        ids = [cid for r in results if (cid := (r.get("content") or {}).get("id"))]
        return ids[:limit]

    async def get_page_children(self, page_id: str) -> dict:
        return await self._get(f"/wiki/api/v2/pages/{page_id}/children")

    async def get_page_attachments(self, page_id: str) -> dict:
        return await self._get(f"/wiki/api/v2/pages/{page_id}/attachments")
