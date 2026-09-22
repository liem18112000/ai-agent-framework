"""InMemoryCache — a per-process dict cache with optional TTL. For local runs + tests.

Per-instance only (NOT shared across Cloud Run instances) — use RedisCache for a shared cache.
"""

from __future__ import annotations

import time


class InMemoryCache:
    def __init__(self) -> None:
        self._store: dict[str, tuple[str, float | None]] = {}  # key → (value, expiry_monotonic | None)

    def get(self, key: str) -> str | None:
        item = self._store.get(key)
        if item is None:
            return None
        value, expiry = item
        if expiry is not None and time.monotonic() >= expiry:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: str, *, ttl: int | None = None) -> None:
        self._store[key] = (value, time.monotonic() + ttl if ttl else None)

    def delete(self, key: str) -> None:
        self._store.pop(key, None)
