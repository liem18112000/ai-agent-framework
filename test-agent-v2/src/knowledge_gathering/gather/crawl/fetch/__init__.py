"""Fetch + extract a single node into (links, note, text)."""

from __future__ import annotations

from common.models import LinkRecord, Note, Scope
from knowledge_gathering.gather.crawl.fetch import (  # noqa: F401  (registration)
    attachment,
    bitbucket,
    cloud_service,
    codegraph,
    confluence,
    github,
    jira,
    web,
)
from knowledge_gathering.gather.crawl.fetch.base import NodeFetcher

__all__ = ["NodeFetcher", "fetch_node"]


async def fetch_node(client, nid: str, scope: Scope) -> tuple[list[LinkRecord], Note, str]:
    kind, _, ident = nid.partition(":")
    fetcher = NodeFetcher.registry.get(kind)
    if fetcher is None:
        raise ValueError(f"unfetchable node: {nid}")
    return await fetcher.fetch(client, ident, nid, scope)
