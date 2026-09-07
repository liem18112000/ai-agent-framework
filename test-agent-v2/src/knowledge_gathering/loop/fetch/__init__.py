"""Fetch + extract a single node into (links, note, text).

A node id is ``"<kind>:<ident>"``; the prefix selects a per-kind NodeFetcher (see base.py).
Adding a source = add a module here + import it below; ``fetch_node`` never changes (Open/Closed).
"""

from __future__ import annotations

from common.models import LinkRecord, Note, Scope

# Import the concrete fetchers so they self-register with NodeFetcher.registry.
from knowledge_gathering.loop.fetch import (  # noqa: F401  (registration)
    bitbucket,
    codegraph,
    confluence,
    jira,
    web,
)
from knowledge_gathering.loop.fetch.base import NodeFetcher

__all__ = ["NodeFetcher", "fetch_node"]


async def fetch_node(client, nid: str, scope: Scope) -> tuple[list[LinkRecord], Note, str]:
    kind, _, ident = nid.partition(":")
    fetcher = NodeFetcher.registry.get(kind)
    if fetcher is None:
        raise ValueError(f"unfetchable node: {nid}")
    return await fetcher.fetch(client, ident, nid, scope)
