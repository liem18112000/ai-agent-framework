"""Generate test scenarios from a confirmed plan (heuristic; POC)."""

from __future__ import annotations

import os

from common.memory.bank import _slug
from common.testplan.models import (
    BOUNDARY,
    ERROR,
    HAPPY,
    NEGATIVE,
    TestData,
    TestPlan,
    TestScenario,
    effective_kinds,
)
from common.testplan.pack import PlanPack
from test_plan_definition.monitoring import get_logger

log = get_logger("implement.generate.scenarios")

# Q2: the four defaults are only a SEED — the kind taxonomy is open and ADDITIVE. `effective_kinds`
# unions the elicited `plan.test_kinds` (case-design round) on top of the four, so user-added kinds
# (security, performance, concurrency, …) flow through WITHOUT ever dropping the base four. No cap on
# kinds, no cap on notes/cases (§ report Q2).
_KIND_SUFFIX = {
    HAPPY: "happy path",
    NEGATIVE: "negative — invalid/unauthorized input is rejected",
    BOUNDARY: "boundary — empty / single / maximum limits",
    ERROR: "error handling — dependency/failure path",
}
_KIND_RATIONALE = {
    HAPPY: "confirms the primary success path works end to end",
    NEGATIVE: "confirms invalid or unauthorized input is safely rejected with no side effects",
    BOUNDARY: "confirms correct behaviour at the input limits (empty / single / maximum)",
    ERROR: "confirms graceful failure and a consistent end state when a dependency fails",
}


def _coverage_kinds(plan: TestPlan) -> tuple[str, ...]:
    """The kinds to cover: the base four ∪ the plan's elicited extras (additive, never a closed set),
    or just happy when the metrics call for happy-only. See ``effective_kinds`` — the single resolver."""
    return tuple(effective_kinds(plan))


def _norm_title(s: str) -> str:
    """Fold a title to a dedup key: lowercase, keep alnum, collapse the rest to single spaces."""
    return " ".join("".join(c if c.isalnum() else " " for c in s.lower()).split())


def refine_scenarios(scenarios: list[TestScenario], valid_ids: set[str]) -> list[TestScenario]:
    """P2 deterministic post-gen cleanup that lifts the judge's traceability + non_duplication scores:
    drop scenarios that cite no REAL pack id (invented/empty source_refs), then drop near-duplicates
    (same kind + folded title). Lenient id match (substring either way) tolerates 'LUZ-1' vs 'jira:LUZ-1'
    so real scenarios are never dropped on format drift. Order-preserving; a no-op on already-clean sets."""
    def traceable(sc: TestScenario) -> bool:
        return not valid_ids or any(
            ref and any(ref in vid or vid in ref for vid in valid_ids) for ref in sc.source_refs)

    out: list[TestScenario] = []
    seen: set[tuple[str, str]] = set()
    for sc in scenarios:
        if not traceable(sc):
            continue
        key = (sc.kind, _norm_title(sc.title))
        if key in seen:
            continue
        seen.add(key)
        out.append(sc)
    return dedup_by_behaviour(out)


def dedup_by_behaviour(scenarios: list[TestScenario]) -> list[TestScenario]:
    """Cross-source SEMANTIC dedup — the lever past the judge's non-duplication ceiling. The generator
    emits scenarios per source-node, so the SAME behaviour arrives 2-3x worded differently (different
    titles + citations) and the title-only pass above can't fold them. Here we cluster same-kind
    scenarios whose title embeddings are near-identical (cosine >= threshold), keep ONE canonical per
    cluster, and union every merged copy's source_refs + data_refs onto it so all supporting sources
    survive as citations. GRACEFUL: any embedder problem (unconfigured / unreachable / error) returns the
    input unchanged, so offline + Vertex-less paths stay byte-identical. Tunable: TPD_DEDUP_THRESHOLD."""
    if len(scenarios) < 2:
        return scenarios
    try:
        thr = float(os.environ.get("TPD_DEDUP_THRESHOLD", "0.86"))
    except (TypeError, ValueError):
        thr = 0.86
    try:
        from common.memory.pg.embed import _get_embedder
        from common.memory.vector_memory import _cosine

        emb = _get_embedder()
        if not emb.is_configured():
            return scenarios
        vecs = emb.embed_texts([f"{s.kind}: {s.title}" for s in scenarios])
    except Exception as exc:  # noqa: BLE001 — dedup must never break generation
        log.info("dedup_by_behaviour: embedder unavailable (%s) — title-dedup only", exc)
        return scenarios

    reps: list[tuple[int, TestScenario]] = []  # (index into vecs, the kept canonical scenario)
    for i, sc in enumerate(scenarios):
        dup = next((rep for j, rep in reps
                    if rep.kind == sc.kind and _cosine(vecs[i], vecs[j]) >= thr), None)
        if dup is None:
            reps.append((i, sc))
            continue
        for ref in sc.source_refs:  # fold the duplicate's citations onto the canonical copy
            if ref not in dup.source_refs:
                dup.source_refs.append(ref)
        for ref in sc.data_refs:
            if ref not in dup.data_refs:
                dup.data_refs.append(ref)
    merged = [sc for _, sc in reps]
    if len(merged) < len(scenarios):
        log.info("dedup_by_behaviour: %d -> %d scenarios (merged %d cross-source duplicates, thr=%.2f)",
                 len(scenarios), len(merged), len(scenarios) - len(merged), thr)
    return merged


async def generate_scenarios(
    plan: TestPlan, plan_pack: PlanPack, test_data: list[TestData], *, now: str = "", model=None,
) -> list[TestScenario]:
    """The ScenarioGen ``LlmAgent`` (the one default implement LLM call, I3) with a heuristic
    fallback — used whenever no model is configured or the model output is invalid."""
    from test_plan_definition.implement.generate.llm import claude_scenarios

    scs = await claude_scenarios(plan, plan_pack, test_data, now=now, model=model)
    return scs or heuristic_scenarios(plan, plan_pack, test_data, now=now)


def heuristic_scenarios(
    plan: TestPlan, plan_pack: PlanPack, test_data: list[TestData], *, now: str = "",
    only_ids: set[str] | None = None,
) -> list[TestScenario]:
    ctx = plan.context_id
    method = plan.methodology[0] if plan.methodology else "api"
    data_refs = [d.id for d in test_data]
    kinds = _coverage_kinds(plan)

    # Q2: no cap — enumerate EVERY grounded note (fall back to scope only when the pack is empty).
    # `only_ids` narrows to one generation batch's units — the per-batch degrade path in the LLM
    # generator, so a single failed batch falls back for its units alone, not the whole suite.
    targets = ([(n.id, n.title) for n in plan_pack.pack.grounded]
              or [(s, s) for s in plan.scope])
    if only_ids is not None:
        targets = [t for t in targets if t[0] in only_ids]

    return [
        TestScenario(
            id=f"scenario:{ctx}:{_slug(ref)}:{_slug(kind)}", plan_id=plan.id,
            title=f"{title} — {_KIND_SUFFIX.get(kind, kind + ' case')}", kind=kind, methodology=method,
            description=f"Exercise the {kind} case for '{title}' via {method}.",
            rationale=_KIND_RATIONALE.get(kind, f"exercises the {kind} aspect of '{title}'"),
            data_refs=data_refs, source_refs=[ref], created_at=now)
        for ref, title in targets for kind in kinds
    ]
