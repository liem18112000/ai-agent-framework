"""Confluence page fetcher."""

from __future__ import annotations

from common.extract import extract_page_links
from common.models import CONFLUENCE_PAGE, LinkRecord, Note, Scope
from knowledge_gathering.gather.crawl.fetch.base import NodeFetcher


class ConfluenceFetcher(NodeFetcher):
    kind = "confluence"

    async def fetch(self, client, ident: str, nid: str, scope: Scope) -> tuple[list[LinkRecord], Note, str]:
        page = await client.get_page(ident)
        try:
            children = await client.get_page_children(ident)
        except Exception:  # noqa: BLE001 — children are best-effort
            children = None
        links = extract_page_links(page, children, base_url=client.base_url, scope=scope)
        return links, Note(
            id=nid, type=CONFLUENCE_PAGE, title=page.get("title", ""),
            source_url=f"{client.base_url}/wiki/pages/{ident}", links=links,
        ), page.get("body", {}).get("storage", {}).get("value", "")
