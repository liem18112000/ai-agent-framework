"""Cache port — a swappable key→string cache (Redis · in-memory · no-op).

Mirrors the ObjectStore port: stdlib-only import so it is safe to reference anywhere; every concrete
backend (the Redis client library) lives behind its adapter and is imported lazily. A cache is an
OPTIMIZATION — callers must stay correct when it returns None or is the no-op `NullCache`.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Cache(Protocol):
    """A key→string cache. Values are opaque strings (callers serialize, e.g. JSON)."""

    def get(self, key: str) -> str | None:
        """The cached value for `key`, or None on miss / any backend error."""
        ...

    def set(self, key: str, value: str, *, ttl: int | None = None) -> None:
        """Cache `value` under `key`. `ttl` seconds (None → the backend default / no expiry)."""
        ...

    def delete(self, key: str) -> None:
        """Drop `key` if present (idempotent)."""
        ...


class NullCache:
    """The default no-op cache — every get misses; writes are dropped. Zero behavior change."""

    def get(self, key: str) -> str | None:
        return None

    def set(self, key: str, value: str, *, ttl: int | None = None) -> None:
        pass

    def delete(self, key: str) -> None:
        pass
