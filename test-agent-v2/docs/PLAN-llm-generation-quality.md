# PLAN — Raise TPD scenario-generation quality to ≥ 0.70 (assured-loop bar)

**Owner:** (next session) · **Context:** LUZ-158230 exposed it; applies to every ticket.
**Branch:** `feature/test-agent/v2-adk` · **Deployed image:** `…/test-agent-v2:f65c3cc-additive-kinds` (klara-nonprod).

## 0. Where we are / why the score is 0.09

The P4 assured loop is `generate → judge → gate(≥0.70) → reflect → regenerate`
(`src/test_plan_definition/implement/assured/loop.py`). Today it never clears the bar:

1. **Generation returns nothing → heuristic fallback.** `claude_scenarios`
   (`implement/generate/llm.py`) makes ONE call asking for *uncapped, 100%* coverage at
   `_SCEN_MAX_TOKENS=16000`; on empty/schema-invalid/timeout it returns `None`
   (`run_json_agent`, `common/testplan/llm/adk.py`, `_DEFAULT_GEN_TIMEOUT_S=180`) and the loop
   drops to `heuristic_scenarios` (`implement/generate/scenarios.py`).
2. **The heuristic caps at ~0.09** on the judge rubric: templated "Exercise the <kind> case for X"
   stubs have **testability ≈ 0** (no observable Then), **ac_coverage** low (generic, not per-AC),
   **non_duplication** low (near-identical), and enumerate **out-of-scope** pack nodes (faithfulness/
   scope hit). So until the *real* LLM generation succeeds, the score cannot exceed the heuristic.

**The judge rubric that 0.70 is measured against** (`judge_scenarios_prompt`, `JudgeVerdict.score()`
gates on holistic `overall`): `ac_coverage · atomicity · testability · traceability · faithfulness ·
negative_edge_coverage · non_duplication`. "Reward real coverage, punish invention."

→ Two workstreams: **(A) make generation reliably SUCCEED**, then **(B) make its output clear all 7
dimensions.** (A) is the hard gate — (B) is moot while every round degrades.

---

## Phase 0 — Instrument & confirm the failure mode (0.5 d)

Cheap, unblocks everything. Do NOT guess timeout-vs-truncation — measure.

- **P0.1** In `run_json_agent`, log the concrete failure: `TimeoutError` (after N s) vs validation
  `Exception` (schema-invalid) vs empty-state. Include prompt token estimate + raw output length.
- **P0.2** Propagate the reason up to `AssuredReport.note` (not just the generic `_DEGRADED_NOTE`),
  so the client/logs see *why* it degraded each round.
- **P0.3** Read deployed logs to classify the LUZ-158230 case:
  `gcloud logging read 'resource.labels.service_name="test-plan-definition-agent-v2" severity>=WARNING' --project klara-nonprod --freshness 30m`
  Look for `generator timed out after 180s` (→ Phase 1a) vs `generator run failed (<pydantic/…>)`
  (→ Phase 1b, truncation).
- **Exit:** we know whether the block is TIME (180 s) or SIZE (16 k truncation) or CONFIG.

## Phase 1 — Make generation RELIABLE (never silently degrade) (1–2 d)

### 1a. If TIME-bound (timeout at 180 s)
- Raise `TPD_GEN_TIMEOUT_S` to ~300 s via the TPD service env in `deployments/test-agent-v2/services.tf`
  (safe now: liveness grace is 450 s, request timeout 600 s — both already deployed).
- Keep the model call off the event loop so a long generation can't restarve liveness even at 300 s:
  wrap the blocking span in `asyncio.to_thread` (or confirm `litellm.acompletion` is truly async
  end-to-end). Liveness widening (commit `8a6f985`) is a band-aid; this is the real cure.

### 1b. If SIZE-bound (16 k truncation / schema-invalid on rich packs)  ← most likely
The single "generate ALL scenarios, uncapped, 100%" call is the fragile point. Chunk it:
- **P1.1** Batch generation by **requirement unit**: split the pack's grounded notes+insights into
  batches of ~5–8 units; one LLM call per batch (each fits well under 16 k and 180 s); accumulate +
  concat. This TRADES AWAY the I3 one-call contract — **explicitly accept that** (quality > purity);
  keep it bounded (batch count × per-call timeout ≤ budget).
- **P1.2** On truncation, detect invalid JSON and either continue the array (continuation prompt) or
  drop the partial and retry that batch — never silently fall back to the whole-pack heuristic.
- **P1.3** Make the fallback per-batch (only the failed batch degrades), not all-or-nothing.

### 1c. Fallback honesty (either path)
- The heuristic must never masquerade as a passing suite. Keep the degraded flag; surface the count
  of batches that degraded.

**Exit:** on the LUZ-158230 pack, the loop produces LLM-authored scenarios (not the heuristic) on
≥ 90 % of rounds.

## Phase 2 — Clear the 7 rubric dimensions (2–3 d)

Target each judged dimension with a prompt/validation change (`scenarios_prompt`, `prompts.py`):

- **ac_coverage** — inject the explicit list of requirement-unit ids (grounded notes + insights)
  and, on reflect rounds, the coverage matrix's **uncovered (unit × kind) cells** as a checklist
  (`common/testplan/coverage.py` already computes them). Instruct: one scenario per applicable cell.
- **testability** — require a concrete observable **Then**; forbid "it works"/"exercise the case".
  Template the plan's end-state oracles as Then patterns (for LUZ-158230: doc retrievable in
  eArchive, job-history success record written, HTTP 400 on >2 GB, per-document error-report contract
  fields, tenant-isolation not-retrievable-under-other-tenant). Add a post-gen validator that flags
  scenarios whose `expected`/Then is empty or generic.
- **traceability** — post-generation, assert every `source_refs` id ∈ pack ids; drop/repair the rest
  (kills "cites NOTHING" and invented ids).
- **faithfulness + scope precision** — pass IN-SCOPE unit ids AND the OUT-OF-SCOPE ids explicitly;
  instruct to generate ONLY for in-scope units; **post-filter** scenarios citing out-of-scope nodes.
  This simultaneously fixes the pack-noise (precision=0.00: Agentic-Framework S1/S2/S3, self/cross-
  check siblings) and the faithfulness dimension.
- **negative_edge_coverage** — kinds are now additive (fix `f65c3cc`); ensure neg/boundary/error per
  risky behaviour; feed documented boundaries (2 GB / 200 MB, dedup states prior-success/failed/
  partial).
- **non_duplication** — dedup near-identical scenarios post-gen (normalise title+behaviour, drop
  cosine/Jaccard near-dupes); instruct distinct behaviours.
- **atomicity** — one behaviour per scenario (prompt already asks; enforce via the batch = unit map).

**Exit:** on a recorded LUZ-158230 pack, a single successful generation scores ≥ 0.5 overall
(pre-reflect), with testability & traceability ≥ 0.7.

## Phase 3 — Strengthen the reflexion loop (1 d)

- Verify `verdict.reflections` actually reach the next `scenarios_prompt` (the `reflections` arg is
  wired — confirm it's rendered prominently, not buried).
- Raise `TPD_ASSURED_MAX_ITERS` to 3–4 (env in `services.tf`) so the loop has room to climb to 0.70
  within `TPD_ASSURED_BUDGET_S` (bump budget if needed; each round now bounded per Phase 1).
- Optional: perspective-diverse judging (2–3 judges, distinct lenses; gate on median) to reduce judge
  variance — only if single-judge score proves noisy.

## Phase 4 — Offline eval harness (measure ≥0.70 without prod) (1–2 d)

- Extend the existing eval infra (`tests/eval/`, the E-series ADK+RAGAS harness) with a **TPS gate**:
  run the REAL generate+judge against a **recorded** LUZ-158230 pack fixture (Starlette TestClient +
  recorded Atlassian + FakeBucket, per the offline patterns), assert `overall ≥ 0.70`.
- Golden set = the confirmed LUZ-158230 plan + the expected in-scope AC×kind cells + a `must_not_
  retrieve` list (the out-of-scope siblings) to score scope precision deterministically.
- This makes iteration cheap and stops the prod round-trips (each ~2–4 min + liveness risk).

## Phase 5 — Validate the JUDGE itself (0.5 d)

- Before trusting 0.70, confirm the judge isn't miscalibrated-strict: feed it a **known-good,
  human-quality** LUZ-158230 suite and confirm it scores ≥ 0.70. If a good suite scores < 0.70,
  fix the rubric/threshold, not just the generator.

## Phase 6 — Prod rollout & verification (0.5 d)

- Deploy (`bash deploy.sh` full build+apply; classifier is non-deterministic — retry). Delete the
  stale `gs://klara-nonprod-kga-v2-memory/memory/test-plan/<ctx>/assured.json` before re-running so
  the loop starts fresh (a resumed better-old-best blocks improvement).
- Re-run `implement_plan(run-e778a050, guidance=…)` → `get_scenarios` (expect real Given/When/Then,
  multi-kind, in-scope only) → `evaluate_plan` (TPS) → confirm `overall ≥ 0.70`.

---

## Sequencing & estimate
`P0 (0.5) → P1 (1–2) → P2 (2–3) → P3 (1) → P4 (1–2) → P5 (0.5) → P6 (0.5)` ≈ **6.5–9.5 d**.
Critical path: **P1 (reliability) before P2 (quality)** — quality work is unmeasurable while every
round degrades. Build **P4 early** (right after P1) so P2/P3 iterate offline against a real number.

## Key decisions to confirm with the user
1. **Trade away I3 (the 1-LLM-call default)** for batched generation (Phase 1b)? Recommended:
   yes — reliability + quality outweigh the one-call purity; keep it bounded.
2. **Scope-filter to in-scope-only** at generation (Phase 2) — this changes the suite from
   "everything in the pack" to "the ticket's behaviours". Recommended: yes (it's the faithfulness +
   precision fix), but confirm the in-scope set is trustworthy first.
3. **Raise the judge bar's inputs, not the bar** — keep threshold 0.70; fix generation, don't lower
   the gate (unless Phase 5 shows the judge is miscalibrated).

## Files that will be touched
- `src/test_plan_definition/implement/generate/llm.py` (batching, continuation) · `.../generate/scenarios.py`
  (heuristic stays the last-resort; per-batch fallback)
- `src/common/testplan/llm/adk.py` (timeout, off-loop, failure reason) · `.../llm/prompts.py`
  (scenarios_prompt: unit list, oracle Then patterns, scope, uncovered-cell checklist)
- `src/test_plan_definition/implement/assured/loop.py` (surface degrade reason; iters/budget)
- `src/common/testplan/coverage.py` (feed uncovered cells to the prompt) · post-gen validators (new,
  small: traceability ∈ pack, scope filter, near-dup dedup)
- `deployments/test-agent-v2/services.tf` (TPD env: `TPD_GEN_TIMEOUT_S`, `TPD_ASSURED_MAX_ITERS`,
  `TPD_ASSURED_BUDGET_S`)
- `tests/eval/` (new TPS gate + LUZ-158230 golden fixture)

## Guardrails already in place (don't regress)
- Kinds are additive via `effective_kinds` (commit `f65c3cc`) — never revert to `test_kinds or DEFAULTS`.
- Liveness grace 450 s / request 600 s (commit `8a6f985`) — a 300 s generation timeout fits.
- Repo git hook rejects AI-attribution commit trailers — commit plain.
