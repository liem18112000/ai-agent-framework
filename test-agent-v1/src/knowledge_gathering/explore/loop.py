"""G5 self-exploration controller — bounded, resumable multi-round explore loop (default OFF).

Gated by `KGA_EXPLORE_LOOP`. When on, the single pre-crawl fan-out becomes a loop:
fan-out (`expansion_round`) → crawl → reflect → derive next focus → repeat, converging on
marginal yield (a round adds no new node) or a hard budget (max rounds / wall-clock). State is
persisted to GCS by `context_id` so a Cloud Run redeploy/timeout resumes mid-loop.

The core loop needs no LLM: round-N focus is `salient_tokens` over round N-1's node titles
(kept tight — broad token sets over-match). G2/G4 stay optional, flag-gated, round-0 only.
Never raises: any error degrades to the accumulated-so-far result; state writes are best-effort.
"""

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

_STATE_ROOT = "memory/explore"  # GCS: <root>/<context_id>/state.json
_FOCUS_CAP = 6  # keep the derived focus tight — broad token sets over-match
_ANCHOR_CAP = 4  # code-vocabulary tokens carried (prepended) into EVERY round's focus (B2)


def _codegraph_enabled() -> bool:
    """B2 auto-anchor — resolve+build ONE dev-panel repo's codegraph at round 0. Opt-in (default
    OFF): a graphify build is expensive and the repo choice is normally human-confirmed, so the
    loop only auto-builds when `KGA_EXPLORE_CODEGRAPH` is set. Part A (feed an ALREADY-attached
    codegraph into the focus) is always on and needs no flag."""
    return os.environ.get("KGA_EXPLORE_CODEGRAPH", "").lower() in ("1", "true", "yes", "on")


def _ground_promotions_enabled() -> bool:
    """B5 structural grounding gate on promotions — opt-in (default OFF). When on, a round-≥1
    promotion is kept only if it connects to the seed's round-0 graph (a shared epic/component/
    codegraph/link), not merely if it is term-near. Strict grounding can trim legitimate breadth,
    so it is gated by `KGA_EXPLORE_GROUND_PROMOTIONS`."""
    return os.environ.get("KGA_EXPLORE_GROUND_PROMOTIONS", "").lower() in ("1", "true", "yes", "on")


def _codegraph_anchor(notes) -> str:
    """Salient code-vocabulary tokens from any CODEGRAPH note's distilled synopsis (endpoints,
    enums, hubs) — the B2 anchor prepended to every later round's focus so exploration stays on
    the seed's real code instead of drifting into the memory well. `""` when no codegraph attached."""
    syn = " ".join(n.synopsis for n in notes if n.type == CODEGRAPH and n.synopsis)
    return " ".join(salient_tokens(syn)[:_ANCHOR_CAP])


def _devpanel_codegraphs(inventory) -> list[str]:
    """Recorded-only `codegraph:<ws>/<repo>` canonicals a crawl surfaced from Jira dev panels
    (deduped, in discovery order) — the B2 auto-anchor candidates."""
    out: list[str] = []
    for lr in inventory:
        c = lr.canonical_url
        if lr.type == CODEGRAPH and c.startswith("codegraph:") and c not in out:
            out.append(c)
    return out


# --- bounds (env-tunable; defaults keep the loop under the Cloud Run timeout) --- #
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
        result.run = r.run  # latest run-log for summarize_gather's memory pointer
    return new_ids


def _excluded(text: str, exclude_tokens: set[str]) -> bool:
    """B6: True if `text` (a node title) mentions any user-rejected domain token."""
    low = (text or "").lower()
    return any(tok in low for tok in exclude_tokens)


async def run_explore_loop(ex, context, event_queue, seed: str, probe, *, bank, client,
                           extra_seeds: list[str], depth: int, scope, distiller, run_id: str,
                           exclude: str | None = None,
                           ) -> tuple[CrawlResult, list[str], str]:
    """Drive the loop, returning `(accumulated_result, md_blocks, exploration_md)`. Never raises:
    any error degrades to the accumulated-so-far result."""
    start = time.monotonic()
    max_rounds = _env_int("KGA_EXPLORE_MAX_ROUNDS", 3)
    time_budget = _env_float("KGA_EXPLORE_TIME_BUDGET", 300.0)  # hard total across all rounds
    round_nodes = _env_int("KGA_EXPLORE_ROUND_NODES", 20)       # per-round crawl node sub-budget
    round_seconds = _env_float("KGA_EXPLORE_ROUND_SECONDS", 120.0)  # per-round crawl time sub-budget

    st = _load_state(bank, run_id)
    rnd = int(st.get("round", 0) or 0)
    visited: set[str] = set(st.get("visited") or [])
    reflections: list[str] = list(st.get("reflections") or [])
    focus: str = st.get("focus") or probe.terms
    anchor: str = st.get("anchor") or ""  # B2: code-vocabulary tokens prepended to every focus

    seed_norm = normalize_seed(seed)
    # B3 — topic coherence: a STABLE reference of the seed's OWN topic — its terms/title/key plus
    # its round-0 neighborhood (frozen after round 0, incl. the B1 parent). Each later round's focus
    # is scored against THIS, never the growing pack (which compounds drift); a round sharing too
    # few tokens with it has drifted off-seed and stops the loop. Persisted so a resume keeps it.
    seed_ref = set(st.get("ref") or []) or (
        set(salient_tokens(f"{probe.terms} {probe.title}")) | {seed_norm.split(':', 1)[-1].lower()})
    min_coherence = _env_int("KGA_EXPLORE_MIN_COHERENCE", 1)  # min shared tokens; 0 disables B3
    base_extra = list(extra_seeds or [])  # e.g. a recommended codegraph repo — round-0 only
    # B2: a dev-panel codegraph queued at round 0 to build+anchor next round (persisted so a
    # redeploy between round 0 and its build resumes the anchor instead of dropping it).
    carry: list[str] = list(st.get("carry") or [])
    # B5: the seed's OWN graph (round-0 node ids + their link targets), frozen after round 0 and
    # persisted; a round-≥1 promotion must structurally connect to it when grounding is enabled.
    seed_anchor_ids: set[str] = set(st.get("anchor_ids") or [])
    # B6 — negative-signal re-anchor: a human rejection ("not related to zip import") whose tokens
    # prune the bled cluster from the pack and steer the focus away. Persisted + accumulated across
    # calls, so repeated corrections stack and survive a resume.
    exclude_tokens: set[str] = set(st.get("exclude") or []) | set(salient_tokens(exclude or ""))
    result = CrawlResult()
    md_blocks: list[str] = []
    converged = False
    drifted = False  # B3: stopped because a round's focus drifted off the seed's topic

    log.info("explore start: seed=%s resume-round=%d visited=%d budget=%.0fs max_rounds=%d",
             seed, rnd, len(visited), time_budget, max_rounds)

    while rnd < max_rounds and (time.monotonic() - start) < time_budget:
        try:
            # Round 0 explores the seed (title/labels feed optional G2/G4); later rounds explore the
            # focus derived from round N-1's discoveries — no LLM, thin=True so G1 search runs.
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
            new_seeds = [s for s in new_seeds if s not in visited]  # never re-promote a crawled id
            if carry:  # B2: build+anchor the dev-panel codegraph resolved at round 0 (leads the crawl)
                new_seeds = carry + [s for s in new_seeds if s not in carry]
                carry = []

            # B5 — structural grounding gate (opt-in): a round-≥1 promotion must connect to the
            # seed's own round-0 graph, not merely be term-near, so a biased memory match can't bleed
            # in. Round 0 (the seed's own crawl) and the B2 carry are exempt — they ARE the anchor.
            if rnd > 0 and seed_anchor_ids and _ground_promotions_enabled():
                graph, _ = bank.load_index()
                kept = [s for s in new_seeds if graph_grounded(graph, s, seed_anchor_ids)]
                if len(kept) != len(new_seeds):
                    log.info("explore: B5 dropped %d ungrounded promotion(s)", len(new_seeds) - len(kept))
                new_seeds = kept

            # Pre-crawl converge (rounds > 0): nothing new to explore.
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

            # Round 0 crawls seed + base extras + promoted; later rounds crawl only the newly
            # promoted seeds, under the per-round node/time sub-budget.
            if rnd == 0:
                r = await crawl(client, bank, seed, depth=depth, scope=scope, distiller=distiller,
                                run_id=run_id, extra_seeds=(base_extra + new_seeds) or None,
                                max_nodes=round_nodes, max_seconds=crawl_seconds)
            else:
                r = await crawl(client, bank, new_seeds[0], depth=depth, scope=scope,
                                distiller=distiller, run_id=run_id,
                                extra_seeds=new_seeds[1:] or None,
                                max_nodes=round_nodes, max_seconds=crawl_seconds)

            # B6 — prune the rejected cluster: drop crawled notes whose title matches a rejected
            # domain token BEFORE accumulating, so it never enters the pack nor steers the focus.
            if exclude_tokens:
                dropped = [n.id for n in r.notes if _excluded(n.title, exclude_tokens)]
                if dropped:
                    r.notes = [n for n in r.notes if n.id not in dropped]
                    visited.update(dropped)  # mark rejected ids visited so they are never re-promoted
                    log.info("explore: B6 pruned %d rejected node(s): %s", len(dropped), dropped)

            new_ids = _accumulate(result, r, visited)
            reflections.append(
                f"round {rnd}: focus={focus!r}, promoted={len(new_seeds)}, new nodes={len(new_ids)}")

            # B2 — (re)derive the codegraph anchor from any code note attached this round; it
            # persists and leads every later focus so rounds steer by the seed's real code.
            found_anchor = _codegraph_anchor(r.notes)
            if found_anchor:
                anchor = found_anchor
            # Round-0 auto-resolve (opt-in): queue ONE dev-panel repo the seed crawl surfaced to be
            # built+anchored next round — codegraph grounding without a manual repo=. Skipped once a
            # codegraph is already anchored (e.g. a client-provided repo=).
            if rnd == 0 and not anchor and not carry and _codegraph_enabled():
                repos = [c for c in _devpanel_codegraphs(r.inventory) if c not in visited]
                if repos:
                    carry = repos[:1]
                    log.info("explore: B2 auto-anchor — queuing dev-panel codegraph %s", carry[0])

            # B3 — freeze the seed's OWN neighborhood into the coherence reference: round 0 crawls
            # the seed + its structural/promoted neighbors, so their vocabulary DEFINES on-topic.
            # Only round 0 extends the reference; later rounds are measured against it (not the pack).
            if rnd == 0:
                seed_ref |= set(salient_tokens(" ".join(n.title for n in r.notes if n.title)))
                # B5 — freeze the seed's graph: its round-0 nodes + everything they link to (epic,
                # component, codegraph, subtasks). Later promotions ground against THIS, not the pack.
                seed_anchor_ids = {n.id for n in r.notes}
                seed_anchor_ids |= {lr.canonical_url for n in r.notes for lr in n.links}

            # Post-crawl converge: marginal yield exhausted.
            if not new_ids:
                converged = True
                _save_state(bank, run_id, round_=rnd + 1, visited=visited,
                            reflections=reflections, focus=focus, anchor=anchor)
                break

            # Next round's focus = the codegraph anchor (B2) + salient tokens of the new nodes'
            # titles (tight, no LLM). Anchor leads so the focus stays on the seed's code.
            new_id_set = set(new_ids)
            titles = " ".join(n.title for n in r.notes if n.id in new_id_set and n.title)
            anchor_toks = anchor.split()
            # B6: rejected tokens never steer the next round; anchor leads, then fresh title tokens.
            title_toks = [t for t in salient_tokens(titles)
                          if t not in anchor_toks and t not in exclude_tokens]
            next_focus = " ".join((anchor_toks + title_toks)[:_FOCUS_CAP])
            if not next_focus:  # nothing to steer the next round → converge
                converged = True
                _save_state(bank, run_id, round_=rnd + 1, visited=visited,
                            reflections=reflections, focus=focus, anchor=anchor)
                break

            # B3 — topic-coherence stop: score the next focus against the STABLE seed reference
            # (+ the on-topic codegraph anchor). Too few shared tokens = the round drifted off the
            # seed, so stop rather than steer round N+1 by the drift. Convergence is "on-topic AND
            # dry", not merely "no new nodes". Disabled when min_coherence == 0.
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
