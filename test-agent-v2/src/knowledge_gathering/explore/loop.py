"""G5 self-exploration controller — bounded, resumable multi-round explore loop (default OFF)."""

from __future__ import annotations

import os
import re
import time

from common.models import CODEGRAPH
from knowledge_gathering.explore.expand import expansion_round
from knowledge_gathering.explore.index import graph_grounded
from knowledge_gathering.explore.self_seed import salient_tokens
from knowledge_gathering.loop import CrawlResult, crawl
from knowledge_gathering.loop.seed import normalize_seed
from knowledge_gathering.monitoring import get_logger

log = get_logger("explore.loop")

_STATE_ROOT = "memory/explore"
_FOCUS_CAP = 6
_ANCHOR_CAP = 4


def _codegraph_enabled() -> bool:
    """B2 auto-anchor — resolve+build ONE dev-panel repo's codegraph at round 0. Opt-in (default"""
    return os.environ.get("KGA_EXPLORE_CODEGRAPH", "").lower() in ("1", "true", "yes", "on")


def _ground_promotions_enabled() -> bool:
    """B5 structural grounding gate on promotions — opt-in (default OFF). When on, a round-≥1"""
    return os.environ.get("KGA_EXPLORE_GROUND_PROMOTIONS", "").lower() in ("1", "true", "yes", "on")


def _codegraph_anchor(notes) -> str:
    """Salient code-vocabulary tokens from any CODEGRAPH note's distilled synopsis (endpoints,"""
    syn = " ".join(n.synopsis for n in notes if n.type == CODEGRAPH and n.synopsis)
    return " ".join(salient_tokens(syn)[:_ANCHOR_CAP])


def _devpanel_codegraphs(inventory) -> list[str]:
    """Recorded-only `codegraph:<ws>/<repo>` canonicals a crawl surfaced from Jira dev panels"""
    out: list[str] = []
    for lr in inventory:
        c = lr.canonical_url
        if lr.type == CODEGRAPH and c.startswith("codegraph:") and c not in out:
            out.append(c)
    return out


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _slug(s: str) -> str:
    """Path-safe slug of a context id (mirrors common.memory.bank._slug)."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_")


def _state_path(context_id: str) -> str:
    return f"{_STATE_ROOT}/{_slug(context_id) or 'run'}/state.json"


def _load_state(bank, context_id: str) -> dict:
    """Resume state for `context_id`, or `{}` when absent. Best-effort."""
    try:
        return bank.get_json(_state_path(context_id), {}) or {}
    except Exception as exc:  # noqa: BLE001 — missing/broken state starts fresh
        log.warning("explore: state load failed (%s); starting fresh", exc)
        return {}


def _save_state(bank, context_id: str, *, round_: int, visited: set[str],
                reflections: list[str], focus: str, anchor: str = "",
                carry: list[str] | None = None, ref: set[str] | None = None,
                anchor_ids: set[str] | None = None, exclude: set[str] | None = None) -> None:
    """Persist the resume point to GCS (best-effort)."""
    try:
        bank.put_json(_state_path(context_id), {
            "round": round_,
            "visited": sorted(visited),
            "reflections": reflections,
            "focus": focus,
            "anchor": anchor,
            "carry": list(carry or []),
            "ref": sorted(ref or []),
            "anchor_ids": sorted(anchor_ids or []),
            "exclude": sorted(exclude or []),
        })
    except Exception as exc:  # noqa: BLE001 — state writes are best-effort
        log.warning("explore: state save failed (%s); continuing", exc)


def _accumulate(result: CrawlResult, r: CrawlResult, visited: set[str]) -> list[str]:
    """Merge round `r` into `result`, returning the ids new this round (cross-round dedup)."""
    new_ids: list[str] = []
    for n in r.notes:
        if n.id not in visited:
            visited.add(n.id)
            new_ids.append(n.id)
            result.notes.append(n)
    result.inventory.extend(r.inventory)
    result.gaps.extend(g for g in r.gaps if g not in result.gaps)
    if r.run is not None:
        result.run = r.run
    return new_ids


def _excluded(text: str, exclude_tokens: set[str]) -> bool:
    """B6: True if `text` (a node title) mentions any user-rejected domain token."""
    low = (text or "").lower()
    return any(tok in low for tok in exclude_tokens)


async def run_explore_loop(ex, context, event_queue, seed: str, probe, *, bank, client,
                           extra_seeds: list[str], depth: int, scope, distiller, run_id: str,
                           exclude: str | None = None,
                           ) -> tuple[CrawlResult, list[str], str]:
    """Drive the loop, returning `(accumulated_result, md_blocks, exploration_md)`. Never raises:"""
    start = time.monotonic()
    max_rounds = _env_int("KGA_EXPLORE_MAX_ROUNDS", 3)
    time_budget = _env_float("KGA_EXPLORE_TIME_BUDGET", 300.0)
    round_nodes = _env_int("KGA_EXPLORE_ROUND_NODES", 20)
    round_seconds = _env_float("KGA_EXPLORE_ROUND_SECONDS", 120.0)

    st = _load_state(bank, run_id)
    rnd = int(st.get("round", 0) or 0)
    visited: set[str] = set(st.get("visited") or [])
    reflections: list[str] = list(st.get("reflections") or [])
    focus: str = st.get("focus") or probe.terms
    anchor: str = st.get("anchor") or ""

    seed_norm = normalize_seed(seed)
    seed_ref = set(st.get("ref") or []) or (
        set(salient_tokens(f"{probe.terms} {probe.title}")) | {seed_norm.split(':', 1)[-1].lower()})
    min_coherence = _env_int("KGA_EXPLORE_MIN_COHERENCE", 1)
    base_extra = list(extra_seeds or [])
    carry: list[str] = list(st.get("carry") or [])
    seed_anchor_ids: set[str] = set(st.get("anchor_ids") or [])
    exclude_tokens: set[str] = set(st.get("exclude") or []) | set(salient_tokens(exclude or ""))
    result = CrawlResult()
    md_blocks: list[str] = []
    converged = False
    drifted = False

    log.info("explore start: seed=%s resume-round=%d visited=%d budget=%.0fs max_rounds=%d",
             seed, rnd, len(visited), time_budget, max_rounds)

    while rnd < max_rounds and (time.monotonic() - start) < time_budget:
        try:
            exclude = set(visited) | set(base_extra) | {seed_norm}
            if rnd == 0:
                new_seeds, blocks = await expansion_round(
                    bank, client, seed=seed, terms=focus, thin=probe.thin, project=probe.project,
                    title=probe.title, description=probe.description, labels=probe.labels,
                    parent=probe.parent, exclude=exclude)
            else:
                new_seeds, blocks = await expansion_round(
                    bank, client, seed=seed, terms=focus, thin=True, project=probe.project,
                    exclude=exclude, allow_hypothesize=False, allow_leads=False)
            md_blocks.extend(blocks)
            new_seeds = [s for s in new_seeds if s not in visited]
            if carry:
                new_seeds = carry + [s for s in new_seeds if s not in carry]
                carry = []

            if rnd > 0 and seed_anchor_ids and _ground_promotions_enabled():
                graph, _ = bank.load_index()
                kept = [s for s in new_seeds if graph_grounded(graph, s, seed_anchor_ids)]
                if len(kept) != len(new_seeds):
                    log.info("explore: B5 dropped %d ungrounded promotion(s)", len(new_seeds) - len(kept))
                new_seeds = kept

            if rnd > 0 and not new_seeds:
                reflections.append(f"round {rnd}: focus={focus!r}, promoted=0, new nodes=0")
                converged = True
                _save_state(bank, run_id, round_=rnd + 1, visited=visited,
                            reflections=reflections, focus=focus, anchor=anchor)
                break

            remaining = time_budget - (time.monotonic() - start)
            if remaining <= 0:
                break
            crawl_seconds = min(round_seconds, remaining)

            if rnd == 0:
                r = await crawl(client, bank, seed, depth=depth, scope=scope, distiller=distiller,
                                run_id=run_id, extra_seeds=(base_extra + new_seeds) or None,
                                max_nodes=round_nodes, max_seconds=crawl_seconds)
            else:
                r = await crawl(client, bank, new_seeds[0], depth=depth, scope=scope,
                                distiller=distiller, run_id=run_id,
                                extra_seeds=new_seeds[1:] or None,
                                max_nodes=round_nodes, max_seconds=crawl_seconds)

            if exclude_tokens:
                dropped = [n.id for n in r.notes if _excluded(n.title, exclude_tokens)]
                if dropped:
                    r.notes = [n for n in r.notes if n.id not in dropped]
                    visited.update(dropped)
                    log.info("explore: B6 pruned %d rejected node(s): %s", len(dropped), dropped)

            new_ids = _accumulate(result, r, visited)
            reflections.append(
                f"round {rnd}: focus={focus!r}, promoted={len(new_seeds)}, new nodes={len(new_ids)}")

            found_anchor = _codegraph_anchor(r.notes)
            if found_anchor:
                anchor = found_anchor
            if rnd == 0 and not anchor and not carry and _codegraph_enabled():
                repos = [c for c in _devpanel_codegraphs(r.inventory) if c not in visited]
                if repos:
                    carry = repos[:1]
                    log.info("explore: B2 auto-anchor — queuing dev-panel codegraph %s", carry[0])

            if rnd == 0:
                seed_ref |= set(salient_tokens(" ".join(n.title for n in r.notes if n.title)))
                seed_anchor_ids = {n.id for n in r.notes}
                seed_anchor_ids |= {lr.canonical_url for n in r.notes for lr in n.links}

            if not new_ids:
                converged = True
                _save_state(bank, run_id, round_=rnd + 1, visited=visited,
                            reflections=reflections, focus=focus, anchor=anchor)
                break

            new_id_set = set(new_ids)
            titles = " ".join(n.title for n in r.notes if n.id in new_id_set and n.title)
            anchor_toks = anchor.split()
            title_toks = [t for t in salient_tokens(titles)
                          if t not in anchor_toks and t not in exclude_tokens]
            next_focus = " ".join((anchor_toks + title_toks)[:_FOCUS_CAP])
            if not next_focus:
                converged = True
                _save_state(bank, run_id, round_=rnd + 1, visited=visited,
                            reflections=reflections, focus=focus, anchor=anchor)
                break

            ref = seed_ref | set(anchor.split())
            shared = len(set(next_focus.split()) & ref)
            if min_coherence and ref and shared < min_coherence:
                reflections.append(
                    f"round {rnd + 1}: focus={next_focus!r} off-seed "
                    f"(coherence {shared}<{min_coherence}) — stopping")
                drifted = True
                _save_state(bank, run_id, round_=rnd + 1, visited=visited,
                            reflections=reflections, focus=focus, anchor=anchor, carry=carry)
                break

            focus = next_focus
            rnd += 1
            _save_state(bank, run_id, round_=rnd, visited=visited, reflections=reflections,
                        focus=focus, anchor=anchor, carry=carry, ref=seed_ref,
                        anchor_ids=seed_anchor_ids, exclude=exclude_tokens)
        except Exception as exc:  # noqa: BLE001 — a round error degrades to the accumulated result
            log.warning("explore round %d failed (%s); degrading to accumulated result", rnd, exc)
            break

    stop = ("stopped: off-seed drift" if drifted
            else "converged" if converged else "budget/round-limit reached")
    exploration_md = (
        f"Exploration: {len(reflections)} round(s), {len(result.notes)} node(s), {stop}."
    )
    if reflections:
        exploration_md += "\n" + "\n".join(reflections)
    log.info("explore done: %d round(s), %d node(s), %s",
             len(reflections), len(result.notes), stop)
    return result, md_blocks, exploration_md
