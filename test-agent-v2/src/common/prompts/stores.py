"""Prompt-store implementations (P0/P2): Python defaults, and Cloud SQL on top of them.

``PgPromptStore`` wraps ``PyPromptStore`` rather than replacing it — that IS the fail-closed rail: a
key that is unreachable, unpublished, or malformed in the DB falls back to the body compiled into the
image, so the worst case is today's behaviour, never an empty instruction.
"""

from __future__ import annotations

import time
from collections.abc import Mapping

from common.monitoring import get_logger
from common.prompts.port import (
    ENGINES,
    NONE,
    PromptNotFound,
    PromptTemplate,
    declared_vars,
)

log = get_logger("prompts")

_DDL = (
    """CREATE TABLE IF NOT EXISTS prompt_template (
        key             TEXT PRIMARY KEY,
        description     TEXT NOT NULL DEFAULT '',
        engine          TEXT NOT NULL DEFAULT 'none',
        current_version INT  NOT NULL DEFAULT 1
    )""",
    """CREATE TABLE IF NOT EXISTS prompt_version (
        key           TEXT NOT NULL,
        version       INT  NOT NULL,
        body          TEXT NOT NULL,
        required_vars TEXT NOT NULL DEFAULT '',
        created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_by    TEXT NOT NULL DEFAULT 'system',
        note          TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (key, version)
    )""",
    # Additive schema evolution. ADD COLUMN IF NOT EXISTS is idempotent, so an existing deployment
    # gains the column without a migration framework. (A column RENAME or type change would need
    # real migration handling — this trick only covers additions.)
    "ALTER TABLE prompt_version ADD COLUMN IF NOT EXISTS image_sha TEXT NOT NULL DEFAULT \'\'",
)

_SELECT = """SELECT t.key, t.engine, t.current_version, v.body, v.required_vars,
                    v.created_by, v.image_sha
             FROM prompt_template t
             JOIN prompt_version v ON v.key = t.key AND v.version = t.current_version"""

#: `created_by` value written by `prompt_seed`. A row with this author is a copy of an image body.
SEED_AUTHOR = "seed"


def body_sha(body: str) -> str:
    """Stable fingerprint of a prompt body — ties a seeded row to the image it was copied from."""
    import hashlib

    return hashlib.sha256(body.encode("utf-8")).hexdigest()


class PyPromptStore:
    """The bodies compiled into the image — the migration shim and the fallback of last resort."""

    def __init__(self, defaults: Mapping[str, PromptTemplate]):
        self._defaults = dict(defaults)

    def get(self, key: str, *, version: int | None = None) -> PromptTemplate:
        try:
            return self._defaults[key]
        except KeyError:
            raise PromptNotFound(key) from None

    async def refresh(self) -> None:
        """Nothing to load — the defaults are already in memory."""

    def pinned(self) -> dict[str, int]:
        return {k: t.version for k, t in self._defaults.items()}


def validate(key: str, body: str, engine: str, required_vars: tuple[str, ...], *,
             contract: tuple[str, ...] = (), forbids: tuple[str, ...] = ()) -> None:
    """Publish-time rail: reject a template that would render wrong at 3am instead of at publish time.

    Checks the engine is known, the body is non-empty, every ``$name`` is declared, and — P5.1 — that
    the body still honours its key's OUTPUT CONTRACT. That last check is the one that matters now that
    bodies are editable data: the "asked for a bare JSON array while the schema is an object wrapper"
    defect cost three rebuilds, and the compile-time test over the shipped defaults cannot see a body
    typed into `prompt_publish`. An undeclared placeholder, separately, renders as the literal text
    ``$foo`` inside the prompt, which the model reads as an instruction."""
    if engine not in ENGINES:
        raise ValueError(f"prompt {key!r}: unknown engine {engine!r} (expected one of {ENGINES})")
    if not body.strip():
        raise ValueError(f"prompt {key!r}: empty body")
    if engine == NONE:
        undeclared = [v for v in declared_vars(body) if v not in required_vars]
        if undeclared:
            raise ValueError(f"prompt {key!r}: undeclared placeholders {undeclared} "
                             f"(declare them in required_vars or remove the $)")
    missing = [c for c in contract if c not in body]
    if missing:
        raise ValueError(f"prompt {key!r}: body no longer states its required contract {missing} — "
                         "the consuming parser depends on that wording")
    present = [f for f in forbids if f in body]
    if present:
        raise ValueError(f"prompt {key!r}: body contains forbidden wording {present} — "
                         "this key's parser expects the opposite shape")


class PgPromptStore:
    """Cloud SQL-backed, snapshot-served. Reuses the shared async engine (``common.db.get_engine``) —
    the same pool the A2A task store dials, so this adds tables, not infrastructure."""

    def __init__(self, fallback: PyPromptStore, *, ttl_s: float = 300.0):
        self._fallback = fallback
        self._ttl_s = ttl_s
        self._snapshot: dict[str, PromptTemplate] = {}
        self._loaded_at = 0.0

    # --- read path (sync, snapshot-only) ---------------------------------------------------------
    def get(self, key: str, *, version: int | None = None) -> PromptTemplate:
        tpl = self._snapshot.get(key)
        if tpl is None or (version is not None and tpl.version != version):
            return self._fallback.get(key)       # unpublished / stale-pin / not refreshed yet
        if self.is_stale_seed(key, tpl):
            # The row is an untouched COPY of an older image body, and the image has since moved on
            # (a deploy shipped new prompt text). Serving the row would silently run the OLD prompt
            # until someone remembered to re-seed — the exact trap this guards. A HUMAN-edited row is
            # never overridden here: that is a deliberate override and still wins.
            return self._fallback.get(key)
        return tpl

    def is_stale_seed(self, key: str, tpl: PromptTemplate | None = None) -> bool:
        """True when `key`'s row is an unmodified seed whose source image body has changed."""
        tpl = tpl if tpl is not None else self._snapshot.get(key)
        if tpl is None or not tpl.seeded:
            return False
        try:
            base = self._fallback.get(key)
        except PromptNotFound:
            return False
        return bool(tpl.image_sha) and tpl.image_sha != body_sha(base.body)

    def pinned(self) -> dict[str, int]:
        """The version actually serving each key right now — recorded on the run log (P4)."""
        pins = self._fallback.pinned()
        pins.update({k: t.version for k, t in self._snapshot.items()})
        return pins

    def is_stale(self) -> bool:
        return (time.monotonic() - self._loaded_at) > self._ttl_s

    # --- write / load path (async) ---------------------------------------------------------------
    async def refresh(self, *, force: bool = False) -> None:
        """Load the published snapshot. Best-effort: on any failure we keep serving the last good
        snapshot (or the Python defaults) rather than breaking generation."""
        if not force and self._snapshot and not self.is_stale():
            return
        engine = _engine()
        if engine is None:
            return
        try:
            from sqlalchemy import text

            async with engine.begin() as conn:
                for ddl in _DDL:
                    await conn.execute(text(ddl))
                rows = (await conn.execute(text(_SELECT))).all()
        except Exception as exc:  # noqa: BLE001 — a prompt store must never break the pipeline
            log.warning("prompts: refresh failed (%s); serving %s", exc,
                        "last snapshot" if self._snapshot else "Python defaults")
            return
        snap: dict[str, PromptTemplate] = {}
        for key, eng, ver, body, req, author, img_sha in rows:
            required = tuple(v for v in (req or "").split(",") if v)
            try:
                base = self._fallback.get(key)
                validate(key, body, eng, base.required_vars,
                         contract=base.contract, forbids=base.forbids)
            except (ValueError, PromptNotFound) as exc:
                log.warning("prompts: %s — keeping the Python default for this key", exc)
                continue
            snap[key] = PromptTemplate(key=key, body=body, version=int(ver), engine=eng,
                                       required_vars=required,
                                       seeded=(author == SEED_AUTHOR), image_sha=img_sha or "")
        self._snapshot, self._loaded_at = snap, time.monotonic()
        log.info("prompts: snapshot loaded (%d published key(s))", len(snap))

    async def publish(self, key: str, body: str, *, engine: str = NONE, note: str = "",
                      created_by: str = "admin", image_sha: str = "",
                      required_vars: tuple[str, ...] | None = None) -> int:
        """Append a new version and move the pointer. Returns the new version number."""
        base = self._fallback.get(key)          # raises PromptNotFound for an unknown key
        # The allowed parameter set comes from the KEY'S DEFINITION, never from the submitted body.
        # Deriving it from the body made the rail self-defeating: every placeholder the author typed
        # counted as "declared", so an undeclared $foo could never be rejected (caught live in P5.3).
        # A published body may use FEWER params than the key declares; it must not invent new ones,
        # because the Python caller only supplies the params it computes — a new $foo would render as
        # the literal text "$foo" into the prompt.
        allowed = required_vars if required_vars is not None else base.required_vars
        validate(key, body, engine, allowed, contract=base.contract, forbids=base.forbids)
        required = declared_vars(body)          # persist what THIS body actually uses
        eng = _engine()
        if eng is None:
            raise RuntimeError("no database configured — cannot publish prompts")
        from sqlalchemy import text

        async with eng.begin() as conn:
            for ddl in _DDL:
                await conn.execute(text(ddl))
            nxt = (await conn.execute(
                text("SELECT COALESCE(MAX(version), 0) + 1 FROM prompt_version WHERE key = :k"),
                {"k": key})).scalar_one()
            await conn.execute(
                text("""INSERT INTO prompt_version (key, version, body, required_vars, created_by,
                                                   note, image_sha)
                        VALUES (:k, :v, :b, :r, :c, :n, :s)"""),
                {"k": key, "v": nxt, "b": body, "r": ",".join(required), "c": created_by, "n": note,
                 "s": image_sha or ""})
            await conn.execute(
                text("""INSERT INTO prompt_template (key, engine, current_version)
                        VALUES (:k, :e, :v)
                        ON CONFLICT (key) DO UPDATE SET engine = :e, current_version = :v"""),
                {"k": key, "e": engine, "v": nxt})
        await self.refresh(force=True)
        return int(nxt)

    async def rollback(self, key: str, version: int) -> int:
        """Point ``key`` back at an existing version. No row is ever deleted — the pointer moves.

        **Version 0 is the image default, not a DB row** (the open question P5 had to answer). Rather
        than make "get me back to the known-good shipped body" inexpressible — the exact thing you
        want during an incident — 0 is accepted as a special case: the pointer is set to 0, the JOIN
        in ``_SELECT`` then matches nothing for that key, and ``get`` falls through to the image
        default. Published versions stay in ``prompt_version`` for audit and can be restored."""
        eng = _engine()
        if eng is None:
            raise RuntimeError("no database configured — cannot roll back prompts")
        from sqlalchemy import text

        async with eng.begin() as conn:
            if version != 0:
                found = (await conn.execute(
                    text("SELECT 1 FROM prompt_version WHERE key = :k AND version = :v"),
                    {"k": key, "v": version})).first()
                if not found:
                    raise PromptNotFound(f"{key} v{version}")
            await conn.execute(text("UPDATE prompt_template SET current_version = :v WHERE key = :k"),
                               {"k": key, "v": version})
        await self.refresh(force=True)
        return version

    async def history(self, key: str, limit: int = 20) -> list[dict]:
        """Version log for one key, newest first (the audit surface behind ``prompt_history``)."""
        eng = _engine()
        if eng is None:
            return []
        from sqlalchemy import text

        async with eng.begin() as conn:
            rows = (await conn.execute(
                text("""SELECT version, created_at, created_by, note, length(body)
                        FROM prompt_version WHERE key = :k ORDER BY version DESC LIMIT :n"""),
                {"k": key, "n": limit})).all()
        return [{"version": v, "created_at": str(ts), "created_by": by, "note": note, "chars": n}
                for v, ts, by, note, n in rows]


def _engine():
    """The shared async engine, or None when no DB is configured (local / offline tests)."""
    from common.db import get_engine

    return get_engine()
