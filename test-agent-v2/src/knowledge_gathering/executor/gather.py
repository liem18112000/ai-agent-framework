"""Knowledge Gathering (Step 1) handler — one-shot crawl over A2A."""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict
from typing import NamedTuple

from a2a.server.agent_execution import RequestContext
from a2a.server.events import EventQueue

from common import learn
from common.extract import adf_text
from common.models import CODEGRAPH, Scope
from knowledge_gathering.executor.common import build_bank, build_client, reply
from knowledge_gathering.explore.expand import expansion_round
from knowledge_gathering.loop import CrawlResult, crawl
from knowledge_gathering.loop.seed import normalize_seed
from knowledge_gathering.monitoring import get_logger

log = get_logger("executor.gather")


def _capture_gather(bank, *, context_id: str, seed: str, result) -> None:
    """L3: enqueue an async capture of which repo the seed's code lives in. Only BUILT codegraph
    nodes qualify — their titles are resolved `<ws>/<repo>` slugs; dev-panel-recorded repos stay
    UUID-masked (`{}/{uuid}`) so they're skipped rather than captured as noise."""
    if not learn.capture_enabled("KGA"):
        return
    try:
        repos = sorted({n.title for n in result.notes if n.type == CODEGRAPH and n.title})
        sigs = learn.from_gather(repos, seed_ref=normalize_seed(seed))
        if sigs:
            learn.enqueue(bank, learn.CaptureJob(
                id=f"cap-gather-{context_id}", context_id=context_id, step="gather",
                signals=[asdict(s) for s in sigs]))
    except Exception as exc:  # noqa: BLE001 — capture must not break gather
        log.warning("A2A gather: lesson capture skipped (%s)", exc)

_JIRA_KEY = re.compile(r"[A-Z][A-Z0-9]+-\d+")


def _follow_web_enabled() -> bool:
    """G3 external-web following — opt-in (default OFF). When off, external-web links stay
    recorded-not-fetched and gather is unchanged."""
    return os.environ.get("KGA_FOLLOW_WEB", "").lower() in ("1", "true", "yes", "on")


def _explore_loop_enabled() -> bool:
    """G5 self-exploration controller — opt-in (default OFF). When off, `run_gather` takes the
    single pre-crawl fan-out path, unchanged."""
    return os.environ.get("KGA_EXPLORE_LOOP", "").lower() in ("1", "true", "yes", "on")


class SeedProbe(NamedTuple):
    """One best-effort seed fetch shared by the pre-crawl G0/G1/G2 phases (defaults = neutral).

    - `terms`: summary + labels + components — so a bare key (no words to match) still finds
      prior work in G0/G1.
    - `thin`: little to expand from (short description AND no issuelinks AND no subtasks) — the
      G1 trigger.
    - `project`: key prefix (LUZ-158390 -> LUZ) scoping the G1 JQL, or None.
    - `title` / `description` / `labels`: raw fields the G2 hypothesize step reasons over.
    - `parent`: the seed's structural parent key (epic/story carrying the real AC), or None —
      the B1 climb anchor for a thin container ticket (LUZ-159312 -> LUZ-156281).
    """

    terms: str = ""
    thin: bool = False
    project: str | None = None
    title: str = ""
    description: str = ""
    labels: list[str] | None = None
    parent: str | None = None


async def _seed_probe(client, seed: str) -> SeedProbe:
    """Best-effort single `get_issue` probe of a Jira seed, feeding the pre-crawl expansion phases.
    Any error / non-Jira seed → a neutral `SeedProbe()`; never fails gather."""
    if not _JIRA_KEY.fullmatch(seed):
        return SeedProbe()
    try:
        f = (await client.get_issue(seed)).get("fields", {})
        title = f.get("summary") or ""
        labels = list(f.get("labels") or [])
        components = [c.get("name", "") for c in (f.get("components") or [])]
        terms = " ".join(p for p in [title, *labels, *components] if p)
        description = adf_text(f.get("description")).strip()
        thin = (
            len(description) < 200
            and not (f.get("issuelinks") or [])
            and not (f.get("subtasks") or [])
        )
        parent = (f.get("parent") or {}).get("key") or None
        return SeedProbe(terms, thin, seed.split("-", 1)[0], title, description, labels, parent)
    except Exception as exc:  # noqa: BLE001 — the probe is best-effort
        log.debug("seed probe failed for %s: %s", seed, exc)
        return SeedProbe()


def parse_input(text: str) -> tuple[str | None, int, str | None, str | None]:
    """Return (seed, depth, repo, exclude). `repo` is an optional "<ws>/<repo>" whose graphify code
    graph grounds the technical interrogation; `exclude` is an optional B6 negative-signal phrase
    ("zip import") that prunes that bled cluster from the explore loop and re-anchors the focus."""
    text = text.strip()
    if text.startswith("{"):
        d = json.loads(text)
        exclude = d.get("exclude")
        if isinstance(exclude, list):
            exclude = " ".join(exclude)
        return d.get("seed"), int(d.get("depth", 2)), d.get("repo") or None, (exclude or None)
    seed = re.search(r"[A-Z][A-Z0-9]+-\d+|\d{6,}|https?://\S+", text)
    depth = re.search(r"depth\s+(\d+)", text)
    repo = re.search(r"repo\s+([\w.-]+/[\w.-]+)", text)
    exclude = re.search(r"exclude[=:\s]+(.+?)\s*$", text)
    return ((seed.group(0) if seed else None),
            (int(depth.group(1)) if depth else 2),
            (repo.group(1) if repo else None),
            (exclude.group(1) if exclude else None))


def summarize_gather(result: CrawlResult) -> str:
    followed = sum(lr.in_scope for lr in result.inventory)
    lines = [
        (
            f"Gather complete: {len(result.notes)} nodes, {len(result.inventory)} links "
            f"({followed} in-scope), {len(result.gaps)} gaps."
        ),
        "Nodes: " + ", ".join(n.id for n in result.notes),
    ]
    # Dev-panel repos are recorded, not auto-built (a graphify build can blow the time budget).
    # Surface them so the client re-gathers with repo=<ws>/<repo> (wider budget, real code).
    repos = sorted({
        lr.canonical_url.split(":", 1)[1]
        for lr in result.inventory
        if lr.type == CODEGRAPH and lr.canonical_url.startswith("codegraph:")
    })
    if repos:
        lines.append(
            "Code repos (dev panel): " + ", ".join(repos)
            + " — re-gather with repo=<ws>/<repo> to ground the codegraph."
        )
    if result.gaps:
        lines.append("Gaps (flagged): " + ", ".join(result.gaps))
    lines.append("Memory: gs://<bucket>/memory/index/knowledge-index.json")
    return "\n".join(lines)


async def run_gather(ex, context: RequestContext, event_queue: EventQueue, text: str) -> None:
    seed, depth, repo, exclude = parse_input(text)
    if not seed:
        return await reply(context, event_queue,
                           "Provide a seed, e.g. 'gather LUZ-158390 depth 2'.")
    try:
        client = ex._client or build_client()
        bank = ex._bank or build_bank()
    except Exception as exc:  # noqa: BLE001 — missing config/creds → graceful reply
        return await reply(context, event_queue, f"Config error: {exc}")

    # A repo seeds a `codegraph:<ws>/<repo>` node — graphify clones + parses it (minutes), so
    # widen the crawl budget when one is present.
    extra_seeds = [repo] if repo else []
    max_seconds = 600.0 if repo else 180.0

    # One best-effort probe read of the seed, shared by G0 + G1 + G2.
    probe = await _seed_probe(client, seed)

    # G3 — external-web following (opt-in, default OFF): when on, linked external-web URLs become
    # in_scope + fetchable (capped by Scope.max_web); default keeps them recorded-only.
    scope = Scope(follow_web=True) if _follow_web_enabled() else None
    if scope is not None:
        log.info("A2A gather: KGA_FOLLOW_WEB on — external-web is fetchable (max_web=%d)",
                 scope.max_web)

    # G5 — self-exploration controller (opt-in, default OFF): wraps the fan-out+crawl in a bounded,
    # resumable multi-round loop converging on marginal yield. When off, the single pass below runs.
    if _explore_loop_enabled():
        from knowledge_gathering.explore.loop import run_explore_loop

        result, md_blocks, exploration_md = await run_explore_loop(
            ex, context, event_queue, seed, probe, bank=bank, client=client,
            extra_seeds=extra_seeds, depth=depth, scope=scope, distiller=ex._distiller,
            run_id=context.context_id or "run", exclude=exclude)
        summary = summarize_gather(result)
        for md in md_blocks:
            summary += "\n\n" + md
        if exploration_md:
            summary += "\n\n" + exploration_md
        _capture_gather(bank, context_id=context.context_id or seed, seed=seed, result=result)  # L3
        return await reply(context, event_queue, summary)

    # --- single pre-crawl fan-out (default path) --- #
    new_seeds, md_blocks = await expansion_round(
        bank, client, seed=seed, terms=probe.terms, thin=probe.thin, project=probe.project,
        title=probe.title, description=probe.description, labels=probe.labels,
        parent=probe.parent, exclude=set(extra_seeds))
    extra_seeds += [s for s in new_seeds if s not in extra_seeds]  # dedup, keep repo first

    log.info("A2A gather: seed=%s depth=%s repo=%s new=%s", seed, depth, repo, new_seeds)
    result = await crawl(client, bank, seed, depth=depth, scope=scope, distiller=ex._distiller,
                         run_id=context.context_id or "run",
                         extra_seeds=extra_seeds or None, max_seconds=max_seconds)
    log.info("A2A gather done: %d nodes, %d gaps", len(result.notes), len(result.gaps))
    summary = summarize_gather(result)
    for md in md_blocks:
        summary += "\n\n" + md
    _capture_gather(bank, context_id=context.context_id or seed, seed=seed, result=result)  # L3
    await reply(context, event_queue, summary)
