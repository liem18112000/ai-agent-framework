"""Ports-and-adapters Cache — a swappable key→string cache (Redis/Memorystore · in-memory · no-op)."""

from common.cache.cache import Cache, NullCache
from common.cache.factory import build_cache, get_cache
from common.cache.memory import InMemoryCache

__all__ = ["Cache", "InMemoryCache", "NullCache", "build_cache", "get_cache"]
