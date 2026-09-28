"""Render a CodeGraphResult into the markdown a crawl Note carries into the pack."""

from __future__ import annotations

from common.codegraph.runner import CodeGraphResult


def _basenames(paths: list[str], limit: int = 12) -> str:
    names = [p.rsplit("/", 1)[-1] for p in paths[:limit]]
    extra = f" (+{len(paths) - limit} more)" if len(paths) > limit else ""
    return ", ".join(names) + extra if names else "(none)"


def distill_code_note(result: CodeGraphResult) -> str:
    """Markdown body for the codegraph Note — the code-intelligence distillation."""
    r = result
    lines = [
        f"# Code graph — {r.repo} @ {r.commit}",
        (
            f"{r.files} files · {r.nodes} nodes · {r.edges} edges · {r.communities} communities "
            f"(built {r.built_at}, {r.tool or 'graphify'})."
        ),
        "",
        "## REST endpoints (inbound API surface)",
        _basenames(r.endpoints),
        "",
        "## Dependency clients (outbound calls)",
        _basenames(r.rest_clients),
    ]
    if r.enums:
        lines += ["", "## Key enums (states / codes)"] + [
            f"- **{path.rsplit('/', 1)[-1]}**: {', '.join(members[:16])}"
            for path, members in list(r.enums.items())[:10]
        ]
    if r.god_nodes:
        hubs = ", ".join(f"{g['name']} ({g['edges']})" for g in r.god_nodes[:10])
        lines += ["", "## Core abstractions (most-connected)", hubs]
    return "\n".join(lines)
