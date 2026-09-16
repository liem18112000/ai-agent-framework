"""Benchmark blob I/O — read/write a run's cached Benchmark under memory/benchmarks/ (no scoring).

Two layers: a fast Cache (Redis/Memorystore in prod, no-op by default) in front of the GCS blob that
is the source of truth. Read = cache → GCS (populate on miss); write = GCS then cache (write-through).
"""

from __future__ import annotations

import json

from common.benchmark.model import SCHEMA_VERSION, Benchmark
from common.cache import get_cache
from common.memory.bank import ROOT, _slug

_PREFIX = f"{ROOT}/benchmarks/"


def _key(context_id: str) -> str:
    return f"{_PREFIX}{_slug(context_id)}.json"


def _latency_key(context_id: str) -> str:
    return f"{_PREFIX}{_slug(context_id)}.latency"


def add_latency(context_id: str | None, ms: float) -> None:
    """Accumulate `ms` of server processing time for a run in the cache (bankless — the choke point
    `BridgeSession.ask` has no bank). Captured only when the cache is shared between the caller and
    `compute_benchmark` (offline A/B: one InMemory cache; prod: point both at the same Redis). No-op
    under the default NullCache — latency is a measurement aid, never load-bearing."""
    if not context_id:
        return
    cache, key = get_cache(), _latency_key(context_id)
    prev = cache.get(key)
    # ponytail: get-then-set, not atomic; a run's pipeline calls are serial per context → no lost update.
    cache.set(key, str((float(prev) if prev else 0.0) + ms))


def read_latency(context_id: str) -> float | None:
    """Total accumulated server time (ms) for a run, or None if nothing was recorded (NullCache / miss)."""
    v = get_cache().get(_latency_key(context_id))
    return float(v) if v else None


def _current(d: dict | None) -> Benchmark | None:
    """A Benchmark from a raw dict, but only if it is the current schema (else None → recompute)."""
    if not d:
        return None
    bm = Benchmark.from_dict(d)
    return bm if bm.schema_version == SCHEMA_VERSION else None


def read_benchmark(bank, context_id: str) -> Benchmark | None:
    """The cached Benchmark, or None if absent / older schema. Cache → GCS, populating the cache on miss."""
    key = _key(context_id)
    cache = get_cache()
    hit = cache.get(key)
    if hit is not None:
        bm = _current(json.loads(hit))
        if bm is not None:
            return bm  # stale-schema cache entries fall through to GCS (the source of truth)
    d = bank.get_json(key, None)
    bm = _current(d)
    if bm is not None:
        cache.set(key, json.dumps(d))
    return bm


def write_benchmark(bank, bm: Benchmark) -> str:
    """Persist to GCS (source of truth) then write through to the cache."""
    key = _key(bm.context_id)
    d = bm.as_dict()
    path = bank.put_json(key, d)
    get_cache().set(key, json.dumps(d))
    return path
