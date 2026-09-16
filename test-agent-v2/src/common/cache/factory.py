"""`build_cache()` — select the Cache backend from env (CACHE_BACKEND). `get_cache()` is the singleton."""

from __future__ import annotations

import os
from functools import lru_cache

from common.cache.cache import Cache, NullCache


def build_cache() -> Cache:
    """Select by CACHE_BACKEND: `none` (default, no-op) | `memory` (per-process) | `redis` (Memorystore).

    Redis reads REDIS_HOST (required), REDIS_PORT (6379), CACHE_TTL_SECONDS (default 3600)."""
    backend = os.environ.get("CACHE_BACKEND", "none").lower()
    if backend in ("none", "", "null"):
        return NullCache()
    if backend == "memory":
        from common.cache.memory import InMemoryCache

        return InMemoryCache()
    if backend == "redis":
        from common.cache.redis_cache import RedisCache

        return RedisCache(os.environ["REDIS_HOST"], int(os.environ.get("REDIS_PORT", "6379")),
                          default_ttl=int(os.environ.get("CACHE_TTL_SECONDS", "3600")))
    raise ValueError(f"unknown CACHE_BACKEND: {backend!r}")


@lru_cache(maxsize=1)
def get_cache() -> Cache:
    """The process-wide Cache singleton (built once from env). Call `get_cache.cache_clear()` in tests."""
    return build_cache()
