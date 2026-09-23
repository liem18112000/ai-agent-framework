"""The single pre-crawl fan-out — the reusable expansion round (parallel seed wave)."""

from __future__ import annotations

import asyncio
import os

from knowledge_gathering.gather.explore.planners.schemas import CloudExplorePlan
from knowledge_gathering.gather.explore.seeds.atlassian_search import atlassian_search_seeds
from knowledge_gathering.gather.explore.seeds.cloud_discover import cloud_service_seeds
from knowledge_gathering.gather.explore.seeds.ground_leads import ground_leads
from knowledge_gathering.gather.explore.seeds.self_seed import memory_self_seed, semantic_self_seed
from knowledge_gathering.gather.explore.source_gate import select_sources
from knowledge_gathering.gather.seed import normalize_seed
from knowledge_gathering.monitoring import get_logger

log = get_logger("explore.expand")

_DEFAULT_FANOUT = 4


def fanout_concurrency() -> int:
    """Max concurrent pre-crawl seed producers (env ``KGA_FANOUT_CONCURRENCY``, default 4, min 1). The
    producers hit DISTINCT backends (memory/pgvector, Atlassian, GCP, web), so parallelism cuts the
    fan-out wall-clock Σ→MAX; set 1 to serialize (a low-risk rollback), and it also throttles parallel
    Atlassian/GCP bursts against their rate limits."""
    try:
        return max(1, int(os.environ.get("KGA_FANOUT_CONCURRENCY", _DEFAULT_FANOUT)))
    except ValueError:
        return _DEFAULT_FANOUT


async def _gather_bounded(n: int, labelled: list[tuple[str, object]]) -> list[tuple[str, object]]:
    """Run ``[(key, coro), ...]`` under ``Semaphore(n)``; return ``[(key, result_or_exc), ...]`` in the
    same order. ``return_exceptions`` so one failed producer never kills the wave (per-source degrade)."""
    sem = asyncio.Semaphore(n)

    async def _run(coro):
        async with sem:
            return await coro

    results = await asyncio.gather(*(_run(c) for _, c in labelled), return_exceptions=True)
    return list(zip((k for k, _ in labelled), results))


def _gate_state(seed: str, terms: str, project: str | None, thin: bool) -> str:
    """The shared ticket state the JEV source gate scores all candidates against (sent once)."""
    return f"ticket={seed}\nterms={terms or ''}\nproject={project or ''}\nthin={thin}"


def _seeds_of(key: str, res) -> tuple[list[str], str]:
    """Normalize a producer result to ``(seeds, md)``. ``ground_leads`` returns a 3-tuple
    ``(grounded, unconfirmed, md)``; the rest return ``(seeds, md)``."""
    if key == "ground_leads":
        grounded, _unconfirmed, md = res
        return grounded, md
    return res


async def expansion_round(
    bank,
    client,
    *,
    seed: str,
    terms: str,
    thin: bool,
    project: str | None,
    parent: str | None = None,
    exclude: set[str] | None = None,
    leads: list[str] | None = None,
    explore_cloud: bool = False,
    cloud_max_services: int = 8,
    cloud_plan: CloudExplorePlan | None = None,
) -> tuple[list[str], list[str]]:
    """Run ONE pre-crawl fan-out and return ``(new_seeds, md_blocks)``.

    The I/O-bound seed producers (semantic recall, Atlassian search, lead grounding, cloud discovery)
    run CONCURRENTLY (``KGA_FANOUT_CONCURRENCY``) since each hits a distinct backend; the free, instant
    ``memory_self_seed`` runs first and its seeds join the exclude the parallel wave sees. A default-OFF
    JEV gate (``select_sources``) may drop a candidate it's confident won't pay before the wave fires.

    Under parallelism the producers can't forward-exclude each other's output the way the old serial
    chain did — each sees only the INITIAL exclude, and every producer caps AFTER filtering exclude
    (all `max_seeds=5`, cloud top-8). ponytail: bounded tail-recall — two sources that both surface the
    same id spend a cap slot on it and the post-fan-out dedup drops the overlap, netting one fewer
    unique seed. The A/B (`tools/gather_fanout_ab.py`) measured the ceiling = the cross-source overlap
    count (1 in the worst case tested): `atlassian_search` × `ground_leads` share Jira/Confluence
    id-space (memory folds in first; cloud is disjoint). Upgrade to a post-dedup cap re-fill only if a
    live PQS/recall golden shows a drop.
    """
    exclude = set(exclude or ())
    seed_norm = normalize_seed(seed)
    new_seeds: list[str] = []
    md: dict[str, str] = {}

    def _add(candidates: list[str]) -> None:
        new_seeds.extend(s for s in candidates if s not in new_seeds and s not in exclude)

    # B1 thin-seed structural climb — synchronous; gates the memory/semantic self-seed below.
    climbed = False
    if thin and parent and (parent_norm := normalize_seed(parent)) not in exclude and parent_norm != seed_norm:
        _add([parent_norm])
        md["climb"] = f"Thin seed — climbed to structural parent {parent}"
        climbed = True
        log.info("A2A gather: thin seed=%s → climbed to parent %s", seed, parent)

    # Free, instant, in-memory recall runs first; its seeds join the exclude the parallel wave sees
    # (cheaply recovering part of the old forward-exclude behaviour for the capped producers).
    if not climbed:
        # memory_self_seed does a blocking GCS bank.load_index() → off the event loop (Cloud Run liveness).
        prior_seeds, md["prior"] = await asyncio.to_thread(memory_self_seed, bank, seed, terms)
        _add(prior_seeds)

    base_exclude = exclude | set(new_seeds) | {seed_norm}  # the ONE exclude the whole parallel wave sees

    # Eligible I/O-bound producers (structural guards) → the default-OFF JEV gate drops any it's
    # confident won't pay → the survivors fan out in parallel. `memory_self_seed` is free/instant → never gated.
    candidates: dict = {}
    if not climbed:
        candidates["semantic"] = semantic_self_seed(bank, seed, terms, exclude=base_exclude)
    if thin and terms:
        candidates["atlassian_search"] = atlassian_search_seeds(client, terms, project=project, exclude=base_exclude)
    if leads:
        candidates["ground_leads"] = ground_leads(client, bank, leads, project=project, exclude=base_exclude)
    if explore_cloud:
        candidates["cloud_discover"] = cloud_service_seeds(
            terms, exclude=base_exclude, cloud_max_services=cloud_max_services, plan=cloud_plan)

    fired = select_sources(set(candidates), state=_gate_state(seed, terms, project, thin))
    for key in set(candidates) - fired:  # close the coroutines we won't await (no "never awaited" warning)
        candidates.pop(key).close()

    for key, res in await _gather_bounded(fanout_concurrency(), list(candidates.items())):
        if isinstance(res, BaseException):
            if isinstance(res, asyncio.CancelledError):  # never swallow cancellation (e.g. shutdown)
                raise res
            log.warning("A2A gather: seed producer %r degraded (%s)", key, res)
            continue
        seeds, md[key] = _seeds_of(key, res)
        _add(seeds)
        log.info("A2A gather: seed=%s → %s promoted %d seed(s): %s", seed, key, len(seeds), seeds)

    order = ("climb", "prior", "semantic", "atlassian_search", "ground_leads", "cloud_discover")
    md_blocks = [md[k] for k in order if md.get(k)]
    return new_seeds, md_blocks
