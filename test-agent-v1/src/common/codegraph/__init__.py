"""Code-base intelligence: build a graphify code graph for a Bitbucket repo and store it
versioned in the GCS memory bank.

``build_and_store`` is the reusable, synchronous entrypoint (acquire -> graphify -> GCS). It is
blocking (subprocess + network) by design, so async callers offload it with
``asyncio.to_thread`` — see knowledge_gathering.loop.fetch.codegraph.
"""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from common.codegraph.acquire import acquire_repo
from common.codegraph.distill import distill_code_note
from common.codegraph.runner import CodeGraphResult, build_code_graph
from common.codegraph.store import read_code_meta, read_index, store_code_graph

__all__ = [
    "CodeGraphResult",
    "build_and_store",
    "build_code_graph",
    "distill_code_note",
    "read_code_meta",
    "read_index",
    "store_code_graph",
]


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_and_store(
    bank, ws: str, repo: str, *, ref: str | None = None,
    bb_auth: tuple[str, str] | None = None, timeout: float = 300.0,
) -> CodeGraphResult:
    """Acquire ``<ws>/<repo>``, build its graphify graph, persist it to GCS, return the result.

    Reads ``CODEGRAPH_LOCAL_ROOT`` (a dir holding local clones) to skip the download in dev.
    Blocking — call via ``asyncio.to_thread`` from async code.
    """
    local_root = os.environ.get("CODEGRAPH_LOCAL_ROOT")
    with tempfile.TemporaryDirectory(prefix=f"codegraph-{repo}-") as tmp:
        src, commit = acquire_repo(
            ws, repo, ref, Path(tmp),
            bb_auth=bb_auth, local_root=Path(local_root) if local_root else None, timeout=timeout,
        )
        result = build_code_graph(
            src, repo, commit, _now(), tool="graphify", timeout=timeout,
        )
    store_code_graph(bank, result)
    return result
