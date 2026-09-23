"""Claude-on-Vertex generator for the implement stage — scenarios, the I3 default LLM call. Returns
None (→ heuristic fallback) when unconfigured or the output fails schema. (The other generators are
inlined at their sole call sites: the P4 judge in ``assured.py``, steps in ``steps.py``, test-data in
``testdata.py``.)"""

from __future__ import annotations

import asyncio
import os

from common.adk import agent_model
from common.testplan.llm.adk import build_generator_agent, run_json_agent
from common.testplan.llm.prompts import pack_block, scenarios_prompt, scope_classify_prompt
from common.testplan.llm.schemas import InScope, Scenarios
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
from test_plan_definition.implement.generate import workers
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
# ponytail: sequential (1) not concurrent. Deployed logs showed ALL 5-6 concurrent batches returning
# empty structured-output SIMULTANEOUSLY (no exception, no timeout) → heuristic fallback → ~0.1 score;
# concurrent in-process ADK Runners are the prime suspect. 1 = one batch at a time. Raise if proven safe.
# (A validated concurrency>1 fix was tried and reverted — it fixed the empty-batch bug but Vertex is
# throughput-bound so it bought no speedup; the real lever is the Phase B batch API. See docs.)
_BATCH_CONCURRENCY = 1
# Cap serial LLM batches per round (≈36 units) so one round can't exceed the ~300s MCP idle ceiling on a
# big UNCLASSIFIED pack (classify_in_scope=None). Overflow units get heuristic scenarios — coverage kept,
# just not LLM-quality for the tail. Normal (classified) packs are far under this. Env: TPD_GEN_MAX_BATCHES.
_DEFAULT_MAX_BATCHES = 12


def _max_llm_batches() -> int:
    try:
        return max(1, int(os.environ.get("TPD_GEN_MAX_BATCHES", _DEFAULT_MAX_BATCHES)))
    except ValueError:
        return _DEFAULT_MAX_BATCHES


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

    model = model or agent_model(max_tokens=_SCEN_MAX_TOKENS)
    if model is None:
        return None
    summary = plan_pack.summary_text()
    units = [n.id for n in plan_pack.pack.grounded]
    if in_scope_ids:  # drop out-of-scope sibling/framework nodes from generation (keep as pack context)
        units = [u for u in units if u in in_scope_ids] or units
    # No grounded units (thin/empty pack) → one whole-pack call, unchanged behaviour (batch id list None).
    batches: list[list[str] | None] = [units[i:i + _BATCH_UNITS]
                                       for i in range(0, len(units), _BATCH_UNITS)] or [None]
    if workers.enabled():  # Phase C: distributed generation via a Pub/Sub worker pool; else fall to sync
        import uuid
        distributed = await workers.worker_scenarios(
            plan, plan_pack, test_data, batches=batches, now=now, reflections=reflections,
            max_tokens=_SCEN_MAX_TOKENS, run=uuid.uuid4().hex[:12])
        if distributed:
            distributed = distributed + await _crosscutting_scenarios(
                plan, plan_pack, test_data, model=model, now=now, reflections=reflections)
            valid = {n.id for n in plan_pack.pack.notes} | set(plan.scope)
            return refine_scenarios(distributed, valid) or distributed or None
        log.info("TPD_GEN_MODE=workers produced nothing; using synchronous generation")

    # Bound serial LLM batches so one round stays under the MCP idle ceiling; overflow → heuristic (below).
    overflow_ids: set[str] = set()
    if len(batches) > (cap := _max_llm_batches()):
        overflow_ids = {u for b in batches[cap:] if b for u in b}
        log.warning("scenarios: %d batches over the %d cap; %d overflow units heuristic-filled",
                    len(batches), cap, len(overflow_ids))
        batches = batches[:cap]

    sem = asyncio.Semaphore(_BATCH_CONCURRENCY)

    async def _batch(ids: list[str] | None) -> tuple[list[TestScenario], bool]:
        async with sem:
            agent = build_generator_agent(
                name="tpd_scenario_gen", system=pack_block(summary),
                output_schema=Scenarios, output_key="tpd_scenarios", model=model)
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
    if overflow_ids:  # units beyond the per-round batch cap → heuristic coverage (never dropped silently)
        for s in heuristic_scenarios(plan, plan_pack, test_data, now=now, only_ids=overflow_ids):
            if s.id not in seen:
                seen.add(s.id)
                merged.append(s)
    merged = merged + await _crosscutting_scenarios(
        plan, plan_pack, test_data, model=model, now=now, reflections=reflections)
    # P2 post-gen cleanup: drop invented citations + near-duplicates against the real pack ids (lifts
    # the judge's traceability + non_duplication). Fall back to the raw merge if a strict pass empties it.
    valid_ids = {n.id for n in plan_pack.pack.notes} | set(plan.scope)
    return refine_scenarios(merged, valid_ids) or merged or None


async def _crosscutting_scenarios(plan: TestPlan, plan_pack, test_data: list[TestData], *,
                                  model, now: str, reflections: list[str] | None) -> list[TestScenario]:
    """Generate the plan's CROSS-CUTTING kinds — anything beyond happy/negative/boundary/error, e.g.
    security, i18n/encoding, concurrency, performance — in ONE dedicated call. These apply to the whole
    feature, not a single pack node, so the per-node batches never emit them and the score stalls on
    missing coverage; the plan's test-design methods name the concrete risks (zip bomb, symlink,
    CP437/NFD, pool-size-N, size boundaries…). Returns [] when there are no extra kinds, the model is
    unconfigured, or the output is empty/invalid — never raises, so it can't break the main suite."""
    cross = [k for k in effective_kinds(plan) if k not in (HAPPY, NEGATIVE, BOUNDARY, ERROR)]
    if not cross or model is None:
        return []
    summary = plan_pack.summary_text()
    agent = build_generator_agent(name="tpd_crosscutting_gen", system=pack_block(summary),
                                  output_schema=Scenarios, output_key="tpd_scenarios", model=model)
    data = await run_json_agent(agent, output_key="tpd_scenarios",
                                user=scenarios_prompt(plan, summary, test_data, reflections,
                                                      include_context=False, crosscutting_kinds=cross))
    if data and (scs := Scenarios(**data).to_scenarios(plan, now)):
        log.info("crosscutting: %d scenario(s) for kinds %s", len(scs), cross)
        return scs
    log.info("crosscutting: no scenarios generated (kinds %s)", cross)
    return []
