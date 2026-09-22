"""Code-graph fetcher — treats a whole Bitbucket repo as a node and distills it with graphify.

At a ``codegraph:<ws>/<repo>`` node, builds the repo's graphify graph (thread-offloaded — the
subprocess + network must not block the event loop), stores it versioned in GCS, and returns a
Note carrying the code-intelligence distillation (endpoints, enums, hubs) into the pack.
"""

from __future__ import annotations

import asyncio
import os

from common.codegraph import build_and_store, distill_code_note
from common.executor import (
    build_bank,  # from common (not KG executor) to avoid a loop<-fetch<-executor cycle
)
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
        # ident = "<ws>/<repo>"
        ws, _, repo = ident.partition("/")
        result = await asyncio.to_thread(build_and_store, build_bank(), ws, repo, bb_auth=_bb_auth())
        md = distill_code_note(result)
        # Pre-fill the synopsis with the full code intelligence so crawl.py's distiller doesn't
        # truncate it away (it honors an already-set synopsis).
        note = Note(
            id=nid, type=CODEGRAPH, title=f"{ws}/{repo}",
            source_url=f"https://bitbucket.org/{ws}/{repo}", links=[], synopsis=md,
        )
        return [], note, md
