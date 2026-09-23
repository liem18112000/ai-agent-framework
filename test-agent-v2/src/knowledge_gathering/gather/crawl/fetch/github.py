"""GitHub source-file fetcher (public github.com + GitHub Enterprise Server)."""

from __future__ import annotations

from common.models import GITHUB, LinkRecord, Note, Scope
from knowledge_gathering.gather.crawl.fetch.base import NodeFetcher


class GitHubFetcher(NodeFetcher):
    kind = "github"

    async def fetch(self, client, ident: str, nid: str, scope: Scope) -> tuple[list[LinkRecord], Note, str]:
        parts = ident.split("/")
        owner, repo, ref, fp = parts[0], parts[1], parts[3], "/".join(parts[4:])
        content = await client.get_github_src(owner, repo, fp, ref)
        return [], Note(
            id=nid, type=GITHUB, title=fp,
            source_url=f"{client.github_web}/{owner}/{repo}/blob/{ref}/{fp}", links=[],
        ), content
