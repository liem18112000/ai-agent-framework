"""Offline tests for the Cache port — Null / InMemory / Redis(fake) + the benchmark store-through path."""

from __future__ import annotations

from common.cache import InMemoryCache, NullCache, build_cache
from common.cache.redis_cache import RedisCache


def test_null_cache_always_misses():
    c = NullCache()
    c.set("k", "v")
    assert c.get("k") is None


def test_inmemory_get_set_delete():
    c = InMemoryCache()
    assert c.get("k") is None
    c.set("k", "v")
    assert c.get("k") == "v"
    c.delete("k")
    assert c.get("k") is None


def test_inmemory_ttl_expires(monkeypatch):
    import common.cache.memory as mem

    t = [1000.0]
    monkeypatch.setattr(mem.time, "monotonic", lambda: t[0])
    c = InMemoryCache()
    c.set("k", "v", ttl=10)
    assert c.get("k") == "v"
    t[0] += 11
    assert c.get("k") is None  # expired


def test_build_cache_selects_backend(monkeypatch):
    monkeypatch.setenv("CACHE_BACKEND", "none")
    assert isinstance(build_cache(), NullCache)
    monkeypatch.setenv("CACHE_BACKEND", "memory")
    assert isinstance(build_cache(), InMemoryCache)
    monkeypatch.setenv("CACHE_BACKEND", "bogus")
    try:
        build_cache()
        assert False, "expected ValueError"
    except ValueError:
        pass


class _FakeRedis:
    """Minimal redis.Redis stand-in (records ex so ttl wiring is checked)."""

    def __init__(self):
        self.store: dict[str, str] = {}
        self.ex: dict[str, int | None] = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.store[key], self.ex[key] = value, ex

    def delete(self, key):
        self.store.pop(key, None)


def test_redis_cache_uses_client_and_default_ttl():
    fake = _FakeRedis()
    c = RedisCache(client=fake, default_ttl=3600)
    c.set("k", "v")
    assert fake.store["k"] == "v" and fake.ex["k"] == 3600  # default ttl applied
    assert c.get("k") == "v"
    c.set("k2", "v2", ttl=10)
    assert fake.ex["k2"] == 10  # explicit ttl wins


def test_redis_errors_degrade_to_miss():
    class _Broken:
        def get(self, key):
            raise RuntimeError("down")

        def set(self, key, value, ex=None):
            raise RuntimeError("down")

        def delete(self, key):
            raise RuntimeError("down")

    c = RedisCache(client=_Broken())
    assert c.get("k") is None  # swallowed → miss
    c.set("k", "v")            # swallowed → no raise
    c.delete("k")


def test_benchmark_store_reads_through_cache(monkeypatch):
    """read_benchmark serves from cache without touching GCS on a hit; write_benchmark populates it."""
    from common.benchmark import Benchmark
    from common.benchmark import store as bstore

    cache = InMemoryCache()
    monkeypatch.setattr(bstore, "get_cache", lambda: cache)

    class _NoReadBank:
        """A bank whose GCS read blows up — proves the value came from the cache."""

        def put_json(self, path, obj):
            return path

        def get_json(self, path, default=None):
            raise AssertionError("GCS read should not happen on a cache hit")

    bank = _NoReadBank()
    bstore.write_benchmark(bank, Benchmark(context_id="run-1", ok=True, pqs=0.9))
    got = bstore.read_benchmark(bank, "run-1")
    assert got is not None and got.pqs == 0.9 and got.context_id == "run-1"
