"""Code-graph fetcher — treats a whole Bitbucket repo as a node and distills it with graphify."""

from __future__ import annotations

import asyncio
import os

from common.codegraph import build_and_store, distill_code_note
from common.memory.factory import build_bank
from common.models import CODEGRAPH, LinkRecord, Note, Scope
from knowledge_gathering.loop.fetch.base import NodeFetcher


def _bb_auth() -> tuple[str, str] | None:
    u = os.environ.get("ATLASSIAN_BITBUCKET_USERNAME")
    p = os.environ.get("ATLASSIAN_BITBUCKET_APP_PASSWORD")
    return (u, p) if u and p else None


class CodeGraphFetcher(NodeFetcher):
    kind = "codegraph"

    async def fetch(
        self, client, ident: str, nid: str, scope: Scope
    ) -> tuple[list[LinkRecord], Note, str]:
        ws, _, repo = ident.partition("/")
        result = await asyncio.to_thread(build_and_store, build_bank(), ws, repo, bb_auth=_bb_auth())
        md = distill_code_note(result)
        note = Note(
            id=nid, type=CODEGRAPH, title=f"{ws}/{repo}",
            source_url=f"https://bitbucket.org/{ws}/{repo}", links=[], synopsis=md,
        )
        return [], note, md
