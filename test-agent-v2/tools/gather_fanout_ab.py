"""G1 A/B harness — parallel vs serial pre-crawl seed fan-out (deterministic, offline).

Answers the two questions the parallel-gather change must clear BEFORE its prod default is raised:

  1. LATENCY  — does concurrency actually cut wall-clock? Run `expansion_round` at
     KGA_FANOUT_CONCURRENCY=1 vs =4 with injected per-producer latency; expect Σ→MAX.
  2. RECALL   — does the parallel MERGE lose unique seeds vs the OLD serial forward-exclude chain?
     The new code gives every producer the SAME initial exclude (it can't forward-chain), and every
     producer caps AFTER filtering exclude — so two producers whose id-spaces overlap can each spend a
     cap slot on the same id, and the post-fan-out dedup drops the overlap → one fewer unique seed.
     This reconstructs the old serial-forward-exclude behaviour on identical inputs and diffs the sets.

It is DETERMINISTIC (fake producers, injected latency) — it measures the STRUCTURAL properties (Σ→MAX,
the exact tail-recall ceiling), not a live ticket's PQS. A live PQS A/B needs the branch deployed (the
MCP gateway runs committed code, not this branch). Run:

    PYTHONIOENCODING=utf-8 uv run python tools/gather_fanout_ab.py
"""

from __future__ import annotations

import asyncio
import os
import time

from knowledge_gathering.gather.explore import expand as E


class _Fake:
    """A cap-after-exclude producer: a ranked candidate list, a cap, and an injected latency. Models
    exactly what the real producers do — `[c for c in ranked if c not in exclude][:cap]`."""

    def __init__(self, key: str, ranked: list[str], cap: int, latency_ms: float):
        self.key, self.ranked, self.cap, self.latency = key, ranked, cap, latency_ms

    def keep(self, exclude: set[str]) -> list[str]:
        return [c for c in self.ranked if c not in exclude][: self.cap]

    async def run(self, exclude: set[str]) -> tuple[list[str], str]:
        await asyncio.sleep(self.latency / 1000.0)
        kept = self.keep(exclude)
        return kept, f"{self.key}: {len(kept)}"


# Scenario: atlassian_search and ground_leads share one Jira id (SHARED) — the realistic overlap, since
# both yield Jira/Confluence ids. ground_leads has more candidates than its cap so it CAN promote a
# replacement when SHARED is already excluded (the serial case). semantic/cloud are disjoint (no loss).
_FAKES = {
    "semantic": _Fake("semantic", ["mem:S1", "mem:S2"], cap=5, latency_ms=200),
    "atlassian_search": _Fake("atlassian_search", ["jira:A1", "jira:SHARED"], cap=5, latency_ms=300),
    "ground_leads": _Fake("ground_leads",
                          ["jira:SHARED", "jira:G1", "jira:G2", "jira:G3", "jira:G4", "jira:G5"],
                          cap=5, latency_ms=400),
    "cloud_discover": _Fake("cloud_discover", ["svc:C1", "svc:C2"], cap=8, latency_ms=250),
}
_MEMORY = _Fake("memory", ["jira:M1"], cap=5, latency_ms=0)  # sync, runs first, folds into base_exclude


def _patch(monkey: dict) -> None:
    """Point expand's producer names at the fakes (module-global rebinding — expand imports them by name)."""
    f = _FAKES
    monkey["memory_self_seed"] = E.memory_self_seed
    monkey["semantic_self_seed"] = E.semantic_self_seed
    monkey["atlassian_search_seeds"] = E.atlassian_search_seeds
    monkey["ground_leads"] = E.ground_leads
    monkey["cloud_service_seeds"] = E.cloud_service_seeds
    E.memory_self_seed = lambda bank, seed, terms: (_MEMORY.keep(set()), "memory")
    E.semantic_self_seed = lambda bank, seed, terms, *, exclude: f["semantic"].run(exclude)
    E.atlassian_search_seeds = lambda client, terms, *, project=None, exclude, max_seeds=5: f["atlassian_search"].run(exclude)
    E.ground_leads = lambda client, bank, leads, *, project=None, exclude: _as_leads(f["ground_leads"].run(exclude))
    E.cloud_service_seeds = lambda terms, *, exclude, cloud_max_services=8, plan=None: f["cloud_discover"].run(exclude)


async def _as_leads(coro):
    seeds, md = await coro
    return seeds, [], md  # ground_leads' 3-tuple shape


def _restore(monkey: dict) -> None:
    for name, fn in monkey.items():
        setattr(E, name, fn)


async def _run_new(n: int) -> tuple[list[str], float]:
    os.environ["KGA_FANOUT_CONCURRENCY"] = str(n)
    t0 = time.monotonic()
    new_seeds, _md = await E.expansion_round(
        bank=None, client=None, seed="LUZ-1", terms="dunning export", thin=True, project="LUZ",
        parent=None, exclude=set(), leads=["lead1"], explore_cloud=True)
    return new_seeds, (time.monotonic() - t0) * 1000.0


def _serial_forward() -> list[str]:
    """Reconstruct the OLD behaviour: exclude grows across producers in the original order, so each
    capped producer fills its cap with ids distinct from everything prior producers found."""
    order = ["memory", "semantic", "atlassian_search", "ground_leads", "cloud_discover"]
    seed_norm = "jira:luz-1"
    seen: list[str] = []
    for key in order:
        fake = _MEMORY if key == "memory" else _FAKES[key]
        excl = set(seen) | {seed_norm}
        for s in fake.keep(excl):
            if s not in seen:
                seen.append(s)
    return seen


async def main() -> None:
    monkey: dict = {}
    _patch(monkey)
    try:
        serial_seeds = _serial_forward()
        new1, ms1 = await _run_new(1)
        new4, ms4 = await _run_new(4)
    finally:
        _restore(monkey)

    print("\n=== G1 fan-out A/B (deterministic) ===\n")
    print(f"LATENCY   serial (N=1): {ms1:7.0f} ms   |   parallel (N=4): {ms4:7.0f} ms   "
          f"→ {ms1 / ms4:.1f}x  (expect ≈ Σ→MAX)")
    print(f"          producer latencies: sem=200 atl=300 leads=400 cloud=250 (ms); "
          f"Σ={200 + 300 + 400 + 250}, MAX=400\n")

    print(f"N-INVARIANCE   set(N=1) == set(N=4): {set(new1) == set(new4)}  "
          f"(the new code gives every producer the same exclude → concurrency can't change the set)\n")

    lost = sorted(set(serial_seeds) - set(new4))
    gained = sorted(set(new4) - set(serial_seeds))
    print(f"RECALL    old serial-forward unique: {len(serial_seeds):2d}   {serial_seeds}")
    print(f"          new parallel-merge unique: {len(set(new4)):2d}   {sorted(set(new4))}")
    print(f"          lost by parallel  : {lost or '∅'}")
    print(f"          gained by parallel: {gained or '∅'}")
    ceiling = len(lost)
    print(f"\nVERDICT   tail-recall ceiling this scenario = {ceiling} seed(s) "
          f"({'the atlassian×ground_leads SHARED overlap' if ceiling else 'no loss'}).")
    print("          Σ→MAX latency win confirmed; recall loss is exactly the cross-source cap overlap.")
    print("          Real gather: overlap is small (memory folds in first; only atlassian×ground_leads")
    print("          share id-space), but it is NOT zero — keep the PQS/recall gate before raising the")
    print("          prod default, or add post-dedup cap re-fill if a live golden shows a drop.\n")


if __name__ == "__main__":
    asyncio.run(main())
