"""The Knowledge Gathering loop — a bounded, concurrent frontier crawl."""

from __future__ import annotations

import asyncio
import time

from common.llm.distill import heuristic_distill
from common.models import EXTERNAL_WEB, Note, RunLog, Scope
from knowledge_gathering.gather.crawl.fetch import fetch_node
from knowledge_gathering.gather.crawl.seed import normalize_seed
from knowledge_gathering.models import CrawlResult
from knowledge_gathering.monitoring import get_logger

log = get_logger("loop")


async def crawl(
    client,
    bank,
    seed: str,
    *,
    scope: Scope | None = None,
    depth: int = 2,
    max_nodes: int = 40,
    max_seconds: float = 180.0,
    run_id: str = "run",
    distiller=None,
    concurrency: int = 8,
    extra_seeds: list[str] | None = None,
) -> CrawlResult:
    scope = scope or Scope()
    distiller = distiller or heuristic_distill
    sem = asyncio.Semaphore(concurrency)
    start = time.monotonic()

    frontier: list[tuple[str, int]] = [(normalize_seed(s), 0) for s in [seed, *(extra_seeds or [])]]
    visited: set[str] = set()
    web_promoted: set[str] = set()
    result = CrawlResult()
    log.info("crawl start: seed=%s extra=%s depth=%s max_nodes=%s",
             seed, extra_seeds or [], depth, max_nodes)

    async def fetch(nid: str):
        async with sem:
            return await fetch_node(client, nid, scope)

    while frontier and len(visited) < max_nodes and time.monotonic() - start < max_seconds:
        level: dict[str, int] = {}
        for nid, d in frontier:
            if nid not in visited and nid not in level:
                level[nid] = d
        level_items = list(level.items())[: max_nodes - len(visited)]
        frontier = []
        log.debug("level: fetching %d nodes (visited=%d)", len(level_items), len(visited))

        fetched = await asyncio.gather(
            *(fetch(nid) for nid, _ in level_items), return_exceptions=True
        )
        for (nid, d), res in zip(level_items, fetched):
            visited.add(nid)
            if isinstance(res, BaseException):
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
            if d < depth:
                for lr in links:
                    canon = lr.canonical_url
                    if not (lr.in_scope and canon not in visited and _fetchable(canon, scope)):
                        continue
                    if lr.type == EXTERNAL_WEB and canon not in web_promoted:
                        if len(web_promoted) >= scope.max_web:
                            continue
                        web_promoted.add(canon)
                    frontier.append((canon, d + 1))

    log.info("crawl done: %d nodes, %d links, %d gaps — persisting",
             len(result.notes), len(result.inventory), len(result.gaps))
    for note in result.notes:
        bank.upsert_note(note)
    if result.notes:
        bank.update_index(_add_all(result.notes))
    result.run = RunLog(
        run_id=run_id, seed=seed, params={"depth": depth, "max_nodes": max_nodes},
        sources=[n.id for n in result.notes], nodes_fetched=len(result.notes),
        links_found=len(result.inventory), gaps=result.gaps, confidence="high",
    )
    bank.append_run_log(result.run)
    return result


def _fetchable(canonical: str, scope: Scope) -> bool:
    """Which canonical node ids can be fetched + followed. external-web canonicals ARE the raw"""
    kind = canonical.split(":", 1)[0]
    if kind in ("http", "https"):
        return scope.follow_web
    return kind in ("jira", "confluence", "bitbucket", "codegraph")


def _add_all(notes: list[Note]):
    def mutate(graph):
        for note in notes:
            graph.add_note(note)

    return mutate
