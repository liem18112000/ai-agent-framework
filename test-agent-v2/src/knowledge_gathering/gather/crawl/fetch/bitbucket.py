"""Bitbucket source-file fetcher."""

from __future__ import annotations

from common.models import BITBUCKET, LinkRecord, Note, Scope
from knowledge_gathering.gather.crawl.fetch.base import NodeFetcher


class BitbucketFetcher(NodeFetcher):
    kind = "bitbucket"

    async def fetch(self, client, ident: str, nid: str, scope: Scope) -> tuple[list[LinkRecord], Note, str]:
        parts = ident.split("/")
        ws, repo, ref, fp = parts[0], parts[1], parts[3], "/".join(parts[4:])
        content = await client.get_bitbucket_src(ws, repo, fp, ref)
        return [], Note(
            id=nid, type=BITBUCKET, title=fp,
            source_url=f"https://bitbucket.org/{ws}/{repo}/src/{ref}/{fp}", links=[],
        ), content
