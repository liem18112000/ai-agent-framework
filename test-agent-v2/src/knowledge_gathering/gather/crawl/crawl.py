"""The Knowledge Gathering loop — a bounded, concurrent frontier crawl (+ its `CrawlResult`)."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from common.llm.distill import heuristic_distill
from common.models import EXTERNAL_WEB, LinkRecord, Note, RunLog, Scope
from knowledge_gathering.gather.crawl.fetch import fetch_node
from knowledge_gathering.gather.seed import normalize_seed
from knowledge_gathering.monitoring import get_logger

log = get_logger("loop")


@dataclass
class CrawlResult:
    """The notes, link inventory, gaps, and run-log one crawl produces."""

    notes: list[Note] = field(default_factory=list)
    inventory: list[LinkRecord] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    run: RunLog | None = None


async def crawl(
    client, bank, seed: str, *, scope: Scope | None = None, depth: int = 2, max_nodes: int = 40,
    max_seconds: float = 180.0, run_id: str = "run", distiller=None, concurrency: int = 8,
    extra_seeds: list[str] | None = None, exclude: set[str] | None = None,
) -> CrawlResult:
    scope = scope or Scope()
    distiller = distiller or heuristic_distill
    exclude = exclude or set()
    sem = asyncio.Semaphore(concurrency)
    start = time.monotonic()
    frontier = [(nid, 0) for s in [seed, *(extra_seeds or [])] if (nid := normalize_seed(s)) not in exclude]
    visited, web_promoted, result = set(), set(), CrawlResult()
    log.info("crawl start: seed=%s extra=%s depth=%s max_nodes=%s", seed, extra_seeds or [], depth, max_nodes)

    async def fetch(nid: str):
        async with sem:
            return await fetch_node(client, nid, scope)

    while frontier and len(visited) < max_nodes and time.monotonic() - start < max_seconds:
        level = {nid: d for nid, d in frontier if nid not in visited and nid not in exclude}
        budget = max_nodes - len(visited)
        level_items = list(level.items())[:budget]
        for nid in list(level)[budget:]:  # nodes we can't afford this run are flagged, not dropped silently
            if nid not in result.gaps:
                result.gaps.append(nid)
        frontier = []
        log.debug("level: fetching %d nodes (visited=%d)", len(level_items), len(visited))
        fetched = await asyncio.gather(*(fetch(nid) for nid, _ in level_items), return_exceptions=True)
        for (nid, d), res in zip(level_items, fetched):
            visited.add(nid)
            if isinstance(res, BaseException):
                if isinstance(res, asyncio.CancelledError):  # never swallow cancellation (e.g. shutdown)
                    raise res
                result.gaps.append(nid)
                log.warning("gap: %s unreachable (%s)", nid, res)
                continue
            links, note, text = res
            note.run_id, note.depth = run_id, d
            if not note.synopsis:
                note.synopsis = await asyncio.to_thread(distiller, note, text)
            result.notes.append(note)
            result.inventory.extend(links)
            log.info("fetched %s (d=%d): %d links, %d in-scope",
                     nid, d, len(links), sum(lr.in_scope for lr in links))
            if d >= depth:
                continue
            for lr in links:
                canon = lr.canonical_url
                if not (lr.in_scope and canon not in visited and canon not in exclude and _fetchable(canon, scope)):
                    continue
                if lr.type == EXTERNAL_WEB and canon not in web_promoted:
                    if len(web_promoted) >= scope.max_web:
                        continue
                    web_promoted.add(canon)
                frontier.append((canon, d + 1))

    log.info("crawl done: %d nodes, %d links, %d gaps — persisting",
             len(result.notes), len(result.inventory), len(result.gaps))
    result.run = RunLog(
        run_id=run_id, seed=seed, params={"depth": depth, "max_nodes": max_nodes},
        sources=[n.id for n in result.notes], nodes_fetched=len(result.notes),
        links_found=len(result.inventory), gaps=result.gaps, confidence="high",
    )
    await asyncio.to_thread(_persist, bank, result)  # sync GCS I/O off the event loop (Cloud Run liveness)
    return result


def _persist(bank, result: CrawlResult) -> None:
    """Write the crawl's notes, index, and run-log to the bank — all synchronous GCS I/O, so the caller
    runs this in a worker thread to keep the asyncio event loop free."""
    for note in result.notes:
        bank.upsert_note(note)
    if result.notes:
        bank.update_index(lambda graph: [graph.add_note(n) for n in result.notes])
    bank.append_run_log(result.run)


def _fetchable(canonical: str, scope: Scope) -> bool:
    """Which canonical node ids can be fetched + followed (external-web gated by scope.follow_web)."""
    kind = canonical.split(":", 1)[0]
    return scope.follow_web if kind in ("http", "https") else kind in ("jira", "confluence", "bitbucket", "codegraph")
