"""Claude-on-Vertex generator for the implement stage — scenarios, the I3 default LLM call. Returns
None (→ heuristic fallback) when unconfigured or the output fails schema. (The other generators are
inlined at their sole call sites: the P4 judge in ``assured.py``, steps in ``steps.py``, test-data in
``testdata.py``.)"""

from __future__ import annotations

import asyncio
import contextlib
import os

from common.adk import agent_model
from common.testplan.llm.adk import build_generator_agent, run_json_agent
from common.testplan.llm.prompts import pack_block, scenarios_prompt, scope_classify_prompt
from common.testplan.llm.schemas import InScope, Scenarios
from common.testplan.models import TestData, TestPlan, TestScenario
from test_plan_definition.implement.generate import batch
from test_plan_definition.monitoring import get_logger

log = get_logger("llm.implement")


async def classify_in_scope(plan: TestPlan, plan_pack, *, model=None) -> set[str] | None:
    """One LLM call that returns the pack node ids IN scope for testing THIS ticket, so generation can
    batch over the ticket's own behaviours instead of the whole crawled pack (sibling/framework nodes
    the crawl swept in tank the judge's faithfulness + scope precision). Returns None — meaning 'don't
    filter, keep all' — when unconfigured, on invalid output, or when there are <2 units to choose
    between (nothing to filter). Conservative by design: the prompt says keep-if-unsure, never empty."""
    grounded = plan_pack.pack.grounded
    if len(grounded) < 2:
        return None
    model = model or agent_model()  # inherit the ceiling — a cap truncates the id list mid-JSON
    if model is None:
        return None
    summary = plan_pack.summary_text()
    agent = build_generator_agent(name="tpd_scope_classifier", system=pack_block(summary),
                                  output_schema=InScope, output_key="tpd_scope", model=model)
    data = await run_json_agent(agent, output_key="tpd_scope",
                                user=scope_classify_prompt(plan, summary, grounded,
                                                           understanding=plan_pack.understanding))
    if not data:
        return None
    ids = {i for i in InScope(**data).in_scope_ids if i in {n.id for n in grounded}}
    if ids:
        log.info("scope classifier: %d/%d units in scope", len(ids), len(grounded))
    return ids or None

# The prompt asks for full behaviour×kind coverage ("no cap, aim for 100%"), so a single call's JSON
# array overruns the model's max output on a rich pack (41 units × 7 kinds ≈ 43k tokens ≫ 16k) → the
# array truncates → schema-invalid → silent heuristic fallback (per-node stubs scoring ~0.09). So we
# BATCH the pack's units and generate a bounded slice per call (concurrently), then merge. Each batch's
# output fits well under the ceiling and its own TPD_GEN_TIMEOUT_S — robust to both size and time.
_SCEN_MAX_TOKENS = 128000  # the model's real output ceiling (claude-sonnet-5) — do NOT cap below it
_BATCH_UNITS = 3        # grounded units per generation call — small so verbose real scenarios never truncate
# Concurrent batches. HISTORY: deployed logs showed ALL 5-6 concurrent batches returning empty structured
# output SIMULTANEOUSLY (no exception/timeout) → heuristic fallback → ~0.1 score, so it was pinned to 1.
# Phase A removes the two shared-state suspects (each batch now gets a FRESH model instance below, and
# run_json_agent uses UNIQUE ADK session ids), making >1 safe to try. Default stays 1 until a live run
# confirms the assured score holds; raise via TPD_BATCH_CONCURRENCY. Bounded by the per-project Vertex quota.
_DEFAULT_BATCH_CONCURRENCY = 1


def _batch_concurrency() -> int:
    with contextlib.suppress(KeyError, ValueError, TypeError):
        return max(1, int(os.environ["TPD_BATCH_CONCURRENCY"]))
    return _DEFAULT_BATCH_CONCURRENCY


async def claude_scenarios(plan: TestPlan, plan_pack, test_data: list[TestData], *,
                           now: str = "", model=None, reflections: list[str] | None = None,
                           in_scope_ids: set[str] | None = None) -> list[TestScenario] | None:
    """Generate the scenario suite via Claude-on-Vertex, batched over the pack's grounded units so no
    single call's array can truncate. Returns None only when unconfigured; a batch whose model output
    is empty/invalid degrades to the heuristic for THAT batch's units alone (never the whole suite).
    ``in_scope_ids`` (from the scope classifier) narrows the batched units to the ticket's own nodes."""
    from test_plan_definition.implement.generate.scenarios import (
        heuristic_scenarios,
        refine_scenarios,
    )

    if model is None and agent_model(max_tokens=_SCEN_MAX_TOKENS) is None:
        return None  # no injected model + unconfigured provider → caller degrades to heuristic
    summary = plan_pack.summary_text()
    units = [n.id for n in plan_pack.pack.grounded]
    if in_scope_ids:  # drop out-of-scope sibling/framework nodes from generation (keep as pack context)
        units = [u for u in units if u in in_scope_ids] or units
    # No grounded units (thin/empty pack) → one whole-pack call, unchanged behaviour (batch id list None).
    batches: list[list[str] | None] = [units[i:i + _BATCH_UNITS]
                                       for i in range(0, len(units), _BATCH_UNITS)] or [None]
    if batch.enabled():  # Phase B: one async Vertex batch job over all batches, else fall through to sync
        batched = await batch.run_batch_scenarios(plan, plan_pack, test_data, batches=batches, now=now,
                                                  reflections=reflections, max_tokens=_SCEN_MAX_TOKENS)
        if batched:
            valid = {n.id for n in plan_pack.pack.notes} | set(plan.scope)
            return refine_scenarios(batched, valid) or batched or None
        log.info("TPD_BATCH_MODE=vertex_batch produced nothing; using synchronous generation")

    sem = asyncio.Semaphore(_batch_concurrency())

    async def _batch(ids: list[str] | None) -> tuple[list[TestScenario], bool]:
        async with sem:
            # fresh model per batch so concurrent batches never share one LiteLlm instance (Phase A —
            # the likely race behind the old concurrency=1 pin); an injected model (tests) is reused.
            batch_model = model or agent_model(max_tokens=_SCEN_MAX_TOKENS)
            agent = build_generator_agent(
                name="tpd_scenario_gen", system=pack_block(summary),
                output_schema=Scenarios, output_key="tpd_scenarios", model=batch_model)
            data = await run_json_agent(agent, output_key="tpd_scenarios",
                                        user=scenarios_prompt(plan, summary, test_data, reflections,
                                                              include_context=False, focus_units=ids))
        if data and (scs := Scenarios(**data).to_scenarios(plan, now)):
            return scs, True
        log.warning("scenarios batch %s empty/invalid; heuristic fallback for this batch", ids or "(whole)")
        return heuristic_scenarios(plan, plan_pack, test_data, now=now,
                                   only_ids=set(ids) if ids else None), False

    results = await asyncio.gather(*(_batch(b) for b in batches))  # gather preserves batch order
    if not any(ok for _, ok in results):
        return None  # every batch degraded → let the caller flag 'degraded' + use its full heuristic
    merged: list[TestScenario] = []
    seen: set[str] = set()
    for scs, _ok in results:  # partial degrade: keep the LLM batches, heuristic-fill the failed ones
        for s in scs:
            if s.id not in seen:
                seen.add(s.id)
                merged.append(s)
    # P2 post-gen cleanup: drop invented citations + near-duplicates against the real pack ids (lifts
    # the judge's traceability + non_duplication). Fall back to the raw merge if a strict pass empties it.
    valid_ids = {n.id for n in plan_pack.pack.notes} | set(plan.scope)
    return refine_scenarios(merged, valid_ids) or merged or None
