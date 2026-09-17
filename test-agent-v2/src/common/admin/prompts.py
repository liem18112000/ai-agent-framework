"""P3 — the operable surface over the prompt store: read, publish, roll back, audit.

Lives in ``common.admin`` beside the other operator reports (runs, memory-view, wipe) and is exposed
through the ADMIN group on the MCP gateway — deliberately NOT part of the
``gather → … → implement`` pipeline.
"""

from __future__ import annotations

import json

from common.prompts import PgPromptStore, PromptNotFound, store_for
from common.testplan.llm.templates import DEFAULTS

_MAX_BODY = 4000


def _store():
    return store_for(DEFAULTS)


async def list_prompts() -> str:
    """Every known key, the version now serving it, and where that version came from."""
    store = _store()
    await store.refresh()
    pins = store.pinned()
    rows = ["# Prompts", "", "| key | version | source | chars |", "|---|---|---|---|"]
    for key in sorted(DEFAULTS):
        tpl = store.get(key)
        source = "database" if tpl.version > 0 else "image default"
        rows.append(f"| `{key}` | {pins.get(key, 0)} | {source} | {len(tpl.body)} |")
    rows += ["", "Publish a new body with `prompt_publish`; revert with `prompt_rollback`.",
             "Version 0 always means the body compiled into the image (the fail-closed fallback)."]
    return "\n".join(rows)


async def get_prompt(key: str) -> str:
    """The body currently serving ``key``, with its declared parameters."""
    store = _store()
    await store.refresh()
    try:
        tpl = store.get(key)
    except PromptNotFound:
        return f"No prompt `{key}`. Known keys: {', '.join(sorted(DEFAULTS))}"
    body = tpl.body if len(tpl.body) <= _MAX_BODY else tpl.body[:_MAX_BODY] + "\n… (truncated)"
    return (f"# `{key}` v{tpl.version} ({'database' if tpl.version else 'image default'})\n"
            f"engine: {tpl.engine} · params: {', '.join(tpl.required_vars) or '(none)'}\n\n"
            f"```\n{body}\n```")


async def publish_prompt(payload: str) -> str:
    """Publish a new version. ``payload`` is JSON: {key, body, note?, engine?}.

    JSON rather than positional text because a prompt body is multi-line and contains every character
    a delimiter could use. Validation (§4.5) runs before the write, so a body with an undeclared
    ``$placeholder`` is rejected at publish time rather than rendering as literal text to the model."""
    try:
        data = json.loads(payload)
    except ValueError as exc:
        return f"Invalid JSON payload ({exc}). Expected {{\"key\": ..., \"body\": ...}}."
    key, body = data.get("key"), data.get("body")
    if not key or not body:
        return 'Payload needs both "key" and "body".'
    store = _store()
    if not isinstance(store, PgPromptStore):
        return "No database configured — prompts are served from the image and cannot be published."
    try:
        version = await store.publish(key, body, engine=data.get("engine", "none"),
                                      note=data.get("note", ""), created_by=data.get("by", "admin"))
    except (ValueError, RuntimeError) as exc:
        return f"Rejected: {exc}"
    return (f"Published `{key}` v{version}. It serves the next run that refreshes "
            f"(runs already in flight keep their pinned version).")


async def rollback_prompt(key: str, version: int) -> str:
    """Point ``key`` back at an earlier version. Nothing is deleted — the pointer moves."""
    store = _store()
    if not isinstance(store, PgPromptStore):
        return "No database configured — nothing to roll back."
    try:
        await store.rollback(key, version)
    except PromptNotFound:
        return f"No version {version} for `{key}` — check `prompt_history`."
    except RuntimeError as exc:
        return f"Rejected: {exc}"
    return f"`{key}` now serves v{version}."


async def prompt_history(key: str, limit: int = 20) -> str:
    """The version log for one key, newest first."""
    store = _store()
    if not isinstance(store, PgPromptStore):
        return f"No database configured — `{key}` is served from the image (v0)."
    rows = await store.history(key, limit)
    if not rows:
        return f"No published versions for `{key}` (serving the image default, v0)."
    out = [f"# `{key}` history", "", "| version | when | by | chars | note |", "|---|---|---|---|---|"]
    out += [f"| {r['version']} | {r['created_at']} | {r['created_by']} | {r['chars']} | {r['note']} |"
            for r in rows]
    return "\n".join(out)
