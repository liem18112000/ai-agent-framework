# Implementation Plan — Run Benchmark (TEV)

Add a **benchmark** capability on top of the Test-Evaluation (TEV) agent: score a run,
compare runs, and summarize the K latest runs — with results computed once and cached.

A "benchmark" = the TEV quality scores for one run (`PQS` from `evaluate_pack`, `TPS` from
`evaluate_plan`, plus their components + retrieval highlights), frozen into a small JSON record.

---

## 0. Grounding facts (what constrains the design)

| Fact | Source | Consequence |
|---|---|---|
| `evaluate_pack(bank, ctx, case) -> EvalReport(pqs, components,…)` and `evaluate_plan(bank, ctx, case, detail) -> PlanReport(tps,…)` are **side-effect-free** | `test_evaluation/engine/pack.py:16`, `plan.py:22` | Safe to call in a loop; benchmark just wraps + persists them |
| Deterministic tiers need **no LLM**; judged/semantic tier is opt-in | `pack.py:36`, `plan.py:54` (`trajectory=1.0` placeholder; semantic `None` on default path) | Default benchmark is cheap → no Cloud-Run timeout risk |
| Agents must never import each other; `common` must not import an agent | memory: `test-agent-common-shared-engine`; `build_bank` self-contained | **Compute must live in TEV**; the model+store can live in `common` |
| No run scores persisted anywhere | `common/admin/runs.py:108` | This is the first persisted metric — add a new blob sink |
| `compare_runs` = text set-diff (consensus %), pairwise only | `common/admin/runs.py:253` | Not reusable as a numeric comparator; **reuse `_pct`/`_bucket`/`_run_exists` helpers only** |
| Runs are derived on read from `memory/refine/<ctx>/` blobs; **no run-status field, failures write nothing** | `common/admin/_shared.py:42`; `runs.py:141/165` | "Even failed" ⇒ benchmark record must carry its own `ok`/`error` |
| No single success-OR-fail run-finish funnel | `implement/generate/agent.py:85`, `pipeline.py:70` (success-only) | Eager hook goes in the **gateway** (only cross-agent vantage point) |
| Bridge pattern: `register_tools(mcp, session) -> {name: fn}`, thin `session.ask("<verb> <args>")` forwarders; gateway merges dicts | `gateway/mcp_server.py:50`; `admin_agent/bridge/mcp_server.py:28` | 3 new tools = 3 forwarders + verb dispatch |
| Env-flag pattern `_on(var)` → services.tf env → variables.tf → tfvars | `common/learn/config.py:8`; `deployments/.../services.tf:153` | Wire `BENCHMARK_ON_FINISH` the same way |

---

## 1. Decisions

- **D1 — Single owner = TEV.** All three tools (`benchmark_run`, `compare_benchmarks`,
  `summarize_benchmarks`) live on TEV. Reason: the aggregators must "compute if missing", which
  needs the scoring engine; admin can't reach it without importing TEV. TEV already owns scoring
  and can enumerate runs via `common.admin` (allowed — it's `common`). Admin stays untouched.
- **D2 — Model + GCS sink in `common`, compute in TEV.** `common/benchmark/` holds the `Benchmark`
  dataclass + `read/write_benchmark` (pure blob I/O, no scoring). `test_evaluation/benchmark.py`
  holds `compute_benchmark` (calls the engines) + `load_or_compute` + `compare` + `summarize`.
- **D3 — Storage key:** `memory/benchmarks/<slug(ctx)>.json` via `bank.put_json/get_json`
  (mirrors existing `memory/notes`, `memory/runs` conventions).
- **D4 — Cache-aside with a single choke point.** One function `load_or_compute(bank, ctx,
  recompute=False)`: return cached blob if present and `schema_version` matches, else compute →
  save → return. All 3 tools **and** the eager hook route through it. (Satisfies "if not found,
  calculate then save".)
- **D5 — Eager write hook in the gateway.** Wrap the merged `implement_plan` tool: after it returns
  (success **or** error, via `try/finally`), fire `tev_session.ask("benchmark <ctx>")`. Guarded by
  `BENCHMARK_ON_FINISH` (default on). Runs that stop before implement get their benchmark lazily on
  first read — the two mechanisms together cover "after the process … even failed or success".
- **D6 — Deterministic tier by default.** Benchmark uses the no-LLM eval path; the judged/semantic
  tier is opt-in via `BENCHMARK_JUDGED=1` (kept off in the eager hook to avoid request-thread Vertex
  calls — see memory `implement-serial-vertex-calls-cloudrun-timeout`).
- **D7 — Failed runs are first-class records.** If `compute_benchmark` can't score (no pack/plan, or
  the engine raises), it saves `ok=false` + `error` + whatever partial score it got. Never throws to
  the caller — a benchmark row always exists after a finish.

---

## 2. Data model — `common/benchmark/model.py`

```python
@dataclass
class Benchmark:
    context_id: str
    ok: bool                       # eval computed cleanly
    pqs: float | None              # from evaluate_pack; None if no pack
    tps: float | None              # from evaluate_plan; None if no plan
    pqs_components: dict[str, float]   # faithfulness, ctx_precision, ctx_recall, relevancy, trajectory
    tps_components: dict[str, float]   # fault_detection, brief_groundedness, coverage, oracle_strength, trajectory
    retrieval: dict | None         # {precision, recall, leaked} highlight from pack eval
    seed: str | None
    computed_at: str               # ISO8601 (datetime.now(UTC) — real code, allowed)
    error: str | None              # set when ok=false
    schema_version: int = 1        # bump to invalidate all cached blobs
```

`to_json`/`from_json` round-trip; `read/write_benchmark(bank, ctx[, bm])` in `store.py`.
Enumeration of "K latest" reuses `common.admin.runs.list_runs` ordering (newest-first) — do **not**
re-implement blob listing.

---

## 3. The three tools (TEV bridge — `test_evaluation/bridge/mcp_server.py`)

| Tool | Verb sent to TEV | Behaviour |
|---|---|---|
| `benchmark_run(context_id, recompute=False)` | `benchmark <ctx>` | `load_or_compute` → rendered scorecard (PQS/TPS + components + retrieval, `ok`/error) |
| `compare_benchmarks(context_ids: list[str])` | `compare-benchmarks <a> <b> …` | ≥2 ids; `load_or_compute` each; side-by-side table per component + Δ vs first; guards missing/invalid ids |
| `summarize_benchmarks(k=5)` | `summarize-benchmarks <k>` | `k<10`; take K latest ctx; `load_or_compute` each; table (ctx │ pqs │ tps │ ok) + mean/min/max + best/worst |

TEV agent routing (`test_evaluation/agent.py`): add explicit **prefix dispatch** for the three
`*benchmark*` verbs **before** the existing `_is_plan` pack/plan text-sniff (none of the benchmark
verbs contain "plan", so no collision). Reuse `ops.extract_ctx`.

---

## 4. Architecture — write + read paths

```
 Client ──implement_plan──▶ Gateway ──▶ TPD (implement)                    [run finishes: done | error]
                              │
                              └─(finally, if BENCHMARK_ON_FINISH)─▶ TEV: "benchmark <ctx>"
                                                                     └─ load_or_compute ─▶ evaluate_pack/plan
                                                                                          └─ write memory/benchmarks/<ctx>.json

 Client ──benchmark_run / compare_benchmarks / summarize_benchmarks──▶ Gateway ──▶ TEV
                                                                          └─ load_or_compute (cache-aside)
                                                                             hit → return; miss → compute+save
```

- **Eager (write):** gateway wraps `implement_plan`; fires benchmark on every finish. Deterministic
  tier only, best-effort (a benchmark failure never breaks the implement response).
- **Lazy (read):** every tool goes through `load_or_compute`; a miss (or `schema_version` bump)
  recomputes and saves. This is also what covers runs that never reached implement.

---

## 5. Milestones

**M0 — Model + sink (`common/benchmark/`)** — `model.py` (dataclass + json), `store.py`
(`read/write_benchmark`, key layout). Unit test: round-trip + FakeBucket read/write.

**M1 — Compute core (`test_evaluation/benchmark.py`)** — `compute_benchmark(bank, ctx, judged=False)`
wrapping the engines with try/except → `ok`/`error`; `load_or_compute(recompute)`. Unit test
(offline, FakeBucket + recorded pack/plan): ctx with pack+plan → pqs+tps set; ctx with nothing →
`ok=false` saved; second call hits cache; `recompute=True` overwrites.

**M2 — Aggregators** — `compare(bank, ctxs)` + `summarize(bank, k)` + renderers (reuse
`common/admin/runs.py` `_pct`/`_bucket`). Test: 3 fake benchmarks → compare table + Δ; summarize
top-K with mean/min/max; `k>=10` rejected; unknown ctx guarded.

**M3 — TEV wiring** — verb dispatch in `agent.py`; 3 tools in the TEV bridge. Test: `send_raw_tev`
routing → each verb reaches the right function (fake session, no Vertex).

**M4 — Eager gateway hook** — wrap `implement_plan` in `gateway/mcp_server.py`; `BENCHMARK_ON_FINISH`
flag (`common/learn/config.py` `_on` style). Test: flag on → implement triggers one benchmark call
(recording fake tev session); flag off → no call; TPD error still fires the finally.

**M5 — Deploy wiring** — `deployments/test-agent-v2/variables.tf` (`benchmark_on_finish` bool,
default true; optional `benchmark_judged`), `services.tf` (gateway module env + tev module env),
`terraform.tfvars(.example)`. No new secrets/IAM.

**M6 — Docs + eval** — README tool list; optionally extend `list_runs` table with a cached-benchmark
column (read-only, no compute) so the admin surface shows scores at a glance.

---

## 6. Deferred (ponytail corners — named, with upgrade path)

- **Staleness = version-only.** A cached benchmark is reused until `schema_version` bumps or
  `recompute=True`; a silently re-run pipeline can leave a stale blob. `ponytail:` add a content
  hash of the pack/plan if stale reads bite.
- **Eager hook only at implement-finish.** Earlier-stopping runs rely on lazy read. Add gather/refine
  finish hooks only if "auto-benchmark every run" is actually needed.
- **No trend history.** Per-run blobs only; the offline `metrics/history.py` already models PQS
  trends if a time series is wanted later.
- **Deterministic scores only in the hot path.** Judged/semantic tier stays opt-in; wire it into a
  nightly/off-band job rather than the request thread.

---

## 7. Files touched

**New:** `src/common/benchmark/{__init__,model,store}.py`; `src/test_evaluation/benchmark.py`;
tests under `test-agent-v2/tests/`.
**Modified:** `src/test_evaluation/agent.py`, `src/test_evaluation/bridge/mcp_server.py`,
`src/gateway/mcp_server.py`; `deployments/test-agent-v2/{variables,services}.tf`, `terraform.tfvars*`;
`README`.
**Untouched:** admin agent, TPD, KGA, `compare_runs`.
