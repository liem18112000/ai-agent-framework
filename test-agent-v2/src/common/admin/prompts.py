"""P3 — the operable surface over the prompt store: seed, read, publish, roll back, audit.

Lives in ``common.admin`` beside the other operator reports (runs, memory-view, wipe) and is exposed
through the ADMIN group on the MCP gateway — deliberately NOT part of the
``gather → … → implement`` pipeline.

**Why `prompt_seed` exists.** The store treats the body compiled into the image as version 0 and only
writes a row when someone publishes, so a fresh deployment has EMPTY tables: every key reports
"image default" and there is nothing in Postgres to look at or edit. That is safe but not operable —
you cannot edit what was never written. Seeding copies each in-use body into the database as its
first version, so the prompts you are actually running become visible, diffable, and editable rows.
"""

from __future__ import annotations

import json

from common.prompts import PgPromptStore, PromptNotFound, store_for

_MAX_BODY = 4000


def _registries() -> list[dict]:
    """Every prompt registry in the process, in one list.

    Each module owns its own ``DEFAULTS`` mapping and ``store_for`` caches one store per mapping, so
    the admin surface has to walk all three — otherwise it reports only the testplan keys and the P6
    engine/KGA prompts look like they do not exist."""
    from common.bridge import prompts as bridge
    from common.llm import templates as engine
    from common.testplan.llm import templates as tpd
    from knowledge_gathering.gather.explore.planners import templates as kga
    from test_executor import prompts as exec_prompts

    return [tpd.DEFAULTS, engine.DEFAULTS, kga.DEFAULTS, bridge.DEFAULTS, exec_prompts.DEFAULTS]


def _all_keys() -> dict:
    """key -> its owning defaults mapping."""
    return {k: d for d in _registries() for k in d}


def _store_for_key(key: str):
    for d in _registries():
        if key in d:
            return store_for(d)
    raise PromptNotFound(key)


async def list_prompts() -> str:
    """Every known key, the version now serving it, and whether it lives in the database yet."""
    rows = ["# Prompts", "", "| key | version | source | chars |", "|---|---|---|---|"]
    in_db = 0
    for d in _registries():
        store = store_for(d)
        await store.refresh()
        for key in sorted(d):
            tpl = store.get(key)
            stale = isinstance(store, PgPromptStore) and store.is_stale_seed(key)
            if stale:
                source = "image (seed is stale)"
            elif tpl.version > 0:
                source = "database (edited)" if not tpl.seeded else "database"
            else:
                source = "image default"
            in_db += tpl.version > 0 and not stale
            rows.append(f"| `{key}` | {tpl.version} | {source} | {len(tpl.body)} |")
    total = len(_all_keys())
    rows += ["", f"**{in_db}/{total} served from the database.**"]
    stale_now = [k for k, dd in _all_keys().items()
                 if isinstance(store_for(dd), PgPromptStore) and store_for(dd).is_stale_seed(k)]
    if stale_now:
        rows += ["", ("**" + str(len(stale_now)) + " seeded row(s) are STALE** — the image shipped new "
                      "prompt text and those rows are untouched copies of the old body, so the IMAGE "
                      "is being served (not the row). Run `prompt_seed` to bring the rows back in "
                      "line. Hand-edited rows are never overridden this way.")]
    if in_db < total:
        rows += ["", ("Keys showing `image default` have NO row in Postgres yet — the body compiled "
                      "into the image is serving them. Run `prompt_seed` to copy the in-use bodies "
                      "into the database so they can be viewed and edited there.")]
    rows += ["", ("Publish a new body with `prompt_publish`; revert with `prompt_rollback` "
                  "(version 0 = back to the image default).")]
    return "\n".join(rows)


async def seed_prompts(force: bool = False) -> str:
    """Copy the in-use image bodies into Postgres as their first version.

    Idempotent by default: a key already served from the database is skipped, so re-running after a
    deploy only picks up newly added keys. ``force=True`` publishes a fresh version of every key from
    the current image — use it after an image upgrade to bring the rows back in line with the code."""
    seeded, skipped, failed = [], [], []
    for d in _registries():
        store = store_for(d)
        if not isinstance(store, PgPromptStore):
            return "No database configured — prompts are served from the image and cannot be seeded."
        await store.refresh()
        for key in sorted(d):
            # A STALE seed (row copied from an older image body) is re-seeded even without `force`:
            # the image is the source of truth for rows nobody edited by hand, so a deploy that ships
            # new prompt text should not need anyone to remember this command.
            if not force and store.get(key).version > 0 and not store.is_stale_seed(key):
                skipped.append(key)
                continue
            base = d[key]
            try:
                version = await store.publish(key, base.body, engine=base.engine,
                                              note="seeded from image default", created_by="seed",
                                              required_vars=base.required_vars)
                seeded.append(f"{key} v{version}")
            except (ValueError, RuntimeError) as exc:
                failed.append(f"{key}: {exc}")
    out = [f"# Prompt seed{' (forced)' if force else ''}", ""]
    out += [f"- seeded: {len(seeded)}"] + [f"  - {s}" for s in seeded]
    if skipped:
        out += [f"- already in the database (skipped): {len(skipped)}"]
    if failed:
        out += [f"- FAILED: {len(failed)}"] + [f"  - {f}" for f in failed]
    out += ["", ("`prompt_list` now shows these as `database`. Editing one is `prompt_publish`; "
                 "`prompt_rollback <key> 0` always returns to the image body.")]
    return "\n".join(out)


async def get_prompt(key: str) -> str:
    """The body currently serving ``key``, with its engine and declared parameters."""
    try:
        store = _store_for_key(key)
    except PromptNotFound:
        return f"No prompt `{key}`. Known keys: {', '.join(sorted(_all_keys()))}"
    await store.refresh()
    tpl = store.get(key)
    body = tpl.body if len(tpl.body) <= _MAX_BODY else tpl.body[:_MAX_BODY] + "\n… (truncated)"
    return (f"# `{key}` v{tpl.version} ({'database' if tpl.version else 'image default'})\n"
            f"engine: {tpl.engine} · params: {', '.join(tpl.required_vars) or '(none)'}\n\n"
            f"```\n{body}\n```")


async def publish_prompt(payload: str) -> str:
    """Publish a new version. ``payload`` is JSON: {key, body, note?, engine?}.

    JSON rather than positional text because a prompt body is multi-line and contains every character
    a delimiter could use. Validation runs before the write: the body must keep its key's output
    contract and may not introduce a ``$placeholder`` the key does not declare."""
    try:
        data = json.loads(payload)
    except ValueError as exc:
        return f'Invalid JSON payload ({exc}). Expected {{"key": ..., "body": ...}}.'
    key, body = data.get("key"), data.get("body")
    if not key or not body:
        return 'Payload needs both "key" and "body".'
    try:
        store = _store_for_key(key)
    except PromptNotFound:
        return f"No prompt `{key}`. Known keys: {', '.join(sorted(_all_keys()))}"
    if not isinstance(store, PgPromptStore):
        return "No database configured — prompts are served from the image and cannot be published."
    try:
        version = await store.publish(key, body, engine=data.get("engine", "none"),
                                      note=data.get("note", ""), created_by=data.get("by", "admin"))
    except (ValueError, RuntimeError, PromptNotFound) as exc:
        return f"Rejected: {exc}"
    return (f"Published `{key}` v{version}. It serves the next run that refreshes "
            f"(runs already in flight keep their pinned version).")


async def rollback_prompt(key: str, version: int) -> str:
    """Point ``key`` back at an earlier version. Nothing is deleted — the pointer moves.

    Version 0 is the body compiled into the image: the always-available known-good target."""
    try:
        store = _store_for_key(key)
    except PromptNotFound:
        return f"No prompt `{key}`. Known keys: {', '.join(sorted(_all_keys()))}"
    if not isinstance(store, PgPromptStore):
        return "No database configured — nothing to roll back."
    try:
        await store.rollback(key, version)
    except PromptNotFound:
        return f"No version {version} for `{key}` — check `prompt_history`."
    except RuntimeError as exc:
        return f"Rejected: {exc}"
    target = "the image default" if version == 0 else f"v{version}"
    return f"`{key}` now serves {target}."


async def prompt_history(key: str, limit: int = 20) -> str:
    """The version log for one key, newest first."""
    try:
        store = _store_for_key(key)
    except PromptNotFound:
        return f"No prompt `{key}`. Known keys: {', '.join(sorted(_all_keys()))}"
    if not isinstance(store, PgPromptStore):
        return f"No database configured — `{key}` is served from the image (v0)."
    rows = await store.history(key, limit)
    if not rows:
        return f"No published versions for `{key}` (serving the image default, v0). Run `prompt_seed`."
    out = [f"# `{key}` history", "", "| version | when | by | chars | note |", "|---|---|---|---|---|"]
    out += [f"| {r['version']} | {r['created_at']} | {r['created_by']} | {r['chars']} | {r['note']} |"
            for r in rows]
    return "\n".join(out)
