"""Versioned GCS persistence for code graphs — reuses the MemoryBank primitives.

Layout (mirrors Vinnstack's per-repo graph + built_at, adapted to the GCS memory bank):

    memory/graphify/index.json                     # registry: [meta, ...]
    memory/graphify/<repo>/<commit>/{graph.json,GRAPH_REPORT.md,meta.json}   # immutable snapshot
    memory/graphify/<repo>/latest/{...}            # moving pointer

Versioning = immutable ``<commit>/`` snapshots + a ``latest/`` pointer + GCS object generations.
"""

from __future__ import annotations

from common.codegraph.runner import CodeGraphResult

PREFIX = "memory/graphify"
INDEX = f"{PREFIX}/index.json"


def _slot_paths(repo: str, slot: str) -> dict[str, str]:
    base = f"{PREFIX}/{repo}/{slot}"
    return {"graph": f"{base}/graph.json", "report": f"{base}/GRAPH_REPORT.md", "meta": f"{base}/meta.json"}


def store_code_graph(bank, result: CodeGraphResult) -> dict:
    """Write both the ``<commit>`` snapshot and ``latest`` pointer, then upsert the registry."""
    meta = result.meta()
    for slot in (result.commit, "latest"):
        p = _slot_paths(result.repo, slot)
        bank.put_json(p["graph"], result.graph_json)
        bank.put_text(p["report"], result.report_md)
        bank.put_json(p["meta"], meta)
    _upsert_index(bank, meta)
    return meta


def _upsert_index(bank, meta: dict) -> None:
    rows = [r for r in (bank.get_json(INDEX, []) or []) if r.get("repo") != meta["repo"]]
    rows.append(meta)
    rows.sort(key=lambda r: r.get("repo", ""))
    bank.put_json(INDEX, rows)


def read_index(bank) -> list[dict]:
    return bank.get_json(INDEX, []) or []


def read_code_meta(bank, repo: str, slot: str = "latest") -> dict | None:
    return bank.get_json(_slot_paths(repo, slot)["meta"], None)
