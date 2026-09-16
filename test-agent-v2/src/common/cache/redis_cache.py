"""RedisCache — a shared cache backed by Redis / GCP Memorystore. Adapter behind the Cache port.

The `redis` client is imported lazily (only prod selects this backend), so local/test runs never need
it installed. Every op degrades gracefully: a Redis outage logs a warning and behaves as a miss/no-op,
so the caller falls back to its source of truth (the cache is only an optimization).
"""

from __future__ import annotations

from common.monitoring import get_logger

log = get_logger("cache.redis")


class RedisCache:
    def __init__(self, host: str | None = None, port: int = 6379, *,
                 default_ttl: int | None = None, client=None, **kw) -> None:
        if client is None:
            import redis  # lazy — only prod pulls the dependency

            client = redis.Redis(host=host, port=port, decode_responses=True, socket_timeout=2, **kw)
        self._r = client
        self._default_ttl = default_ttl

    def get(self, key: str) -> str | None:
        try:
            return self._r.get(key)
        except Exception as exc:  # noqa: BLE001 — a cache miss must never break the caller
            log.warning("redis get failed for %s: %s", key, exc)
            return None

    def set(self, key: str, value: str, *, ttl: int | None = None) -> None:
        try:
            self._r.set(key, value, ex=ttl or self._default_ttl)
        except Exception as exc:  # noqa: BLE001 — a failed cache write must never break the caller
            log.warning("redis set failed for %s: %s", key, exc)

    def delete(self, key: str) -> None:
        try:
            self._r.delete(key)
        except Exception as exc:  # noqa: BLE001
            log.warning("redis delete failed for %s: %s", key, exc)
