# PLAN — Latency optimization (two modes)

**Goal.** Cut the wall-clock of the test-agent request/response without (Mode A) or with a
small, opt-in (Mode B) quality trade. Two deliverables:

- **Mode A — "Fast" (no quality loss).** Unconditional changes. Same LLM outputs, fewer/cheaper/cached
  round-trips. Always on.
- **Mode B — "Turbo" (small quality trade).** One `TESTAGENT_TURBO` boolean that flips the aggressive
  knobs. Most of those knobs **already exist as env flags** — Turbo is largely a *named bundle*, not new code.

---

## ▶ Status — resume here (2026-09-16)

**Committed & pushed:** `b767e57` on `feature/test-agent/v2-adk` (15 files, plain message — no AI trailer,
the repo hook rejects those). Full detail in memory note `v2-latency-map-and-plan`.

| Item | State | Where |
|---|---|---|
| **Mode A — A1** reuse AnthropicVertex client | ✅ done | `common/llm/vertex.py` (`_client` lru_cache) |
| **Mode A — A2** prompt-cache refine rounds | ✅ done | `common/llm/questions.py` + `prompts.py` (`include_context=False` + `cache_prefix`) |
| **Mode A — A3** parallelize planners | ❌ dropped | unsafe (shared ADK `ctx.session.state`) + low-value |
| **Phase 0** latency capture | ✅ done | `Benchmark.latency_ms` (`SCHEMA_VERSION` 1→2); `BridgeSession.ask` accumulates via `get_cache()`; `compute_benchmark` reads it |
| **Phase 2** `TESTAGENT_TURBO` toggle | ✅ done | `adk/config.py::turbo_on()` read at 3 gates: assured iters 2→1, critique off, refine passes 4→1 |
| **Phase 3** fast model tier (B5) | ✅ done | `agent_model/complete(tier="fast")` → `VERTEX_MODEL_FAST`; routed at distill/understanding/define-brief/critique/judge; inert until env set |
| **Live A/B** on LUZ-156281 | ⬜ TODO | single-process, `CACHE_BACKEND=memory`, turbo off vs on |
| **TF plumbing** for `TESTAGENT_TURBO` | ⬜ TODO | add env to KGA+TPD in `variables.tf`/`services.tf` |

**Tests:** `tests/test_turbo.py` (3) + a latency case in `tests/eval/test_benchmark.py`; targeted blast-radius
80 pass. Run the **full suite in the foreground** (`python -m pytest tests/ -q`, ~64s) — backgrounding it ran slow.

**Deploy caveats (for the deploy session):**
- `b767e57` is **safe-by-default** — turbo off, latency capture no-op under `NullCache`. Deploying changes nothing on its own.
- **Turbo won't activate** until `TESTAGENT_TURBO=1` is set on the KGA + TPD Cloud Run services (TF plumbing above not done).
- **`latency_ms` is `None` in prod** — gateway and TEV don't share a cache (prod Redis is TEV-only). Latency is an **offline-A/B** metric only.
- `SCHEMA_VERSION` 1→2 invalidates cached `Benchmark` blobs → lazy recompute on next read (harmless).
- Standard v2: direct `terraform apply` is classifier-blocked → `SKIP_BUILD=1 bash deploy.sh`; build image before pointing services; 2Gi already set.

**Reconciled with new code (2026-09-17 review):** the quality workstream (`PLAN-llm-generation-quality.md`)
landed **batched scenario generation** + raised caps to **128000**. Impact on this plan: (a) A2 refine
cache_prefix **survived** the prompts.py template refactor (verified); (b) implement is now **N sequential
batch calls** (`_BATCH_UNITS=3`, `_BATCH_CONCURRENCY=1`) — a bigger, pack-size-scaling sink, so **B1
(iters→1)** matters more; (c) the biggest remaining implement lever, **raising `_BATCH_CONCURRENCY`, is
BLOCKED** — concurrent in-process ADK Runners are prod-proven-broken (same root cause as the dropped A3);
(d) B6-cut is doubly confirmed (128000 = model ceiling to stop truncation).

**Next step when resuming:** either Phase 3 (fast tier — the big Turbo win), the live A/B, or the higher-value
but harder **ADK-concurrency fix** that unblocks `_BATCH_CONCURRENCY` (cuts implement wall-clock the most).

---

## 0. Diagnosis — where the time actually goes

Reframe first: **extended thinking is disabled on every call site** (`common/llm/vertex.py:46`,
`providers/vertex_claude.py:37`, `vertex.py:83` all `thinking={"type":"disabled"}`). So "thinks too long"
is **not** model reasoning tokens. It is the number of **serial LLM round-trips** and a few heavy ones.
`temperature` is never set anywhere; there is **one model tier** (no fast/slow split).

Per-stage cost with **default flags** (verified in code):

| Stage | LLM calls (default) | Serial? | Heaviest thing |
|---|---|---|---|
| **gather (quiet)** | 0 | crawl fetches parallel, `Semaphore(8)` (`crawl/crawl.py:55`) | codegraph build: git-clone + graphify, **up to 300s** (`crawl/fetch/codegraph.py:25`) when a `repo` node is crawled |
| **gather (explore=on)** | 2–3 × 400-tok planners | **SERIAL** (`gather/agent.py:71,77,82`) | independent planners run one after another |
| **refine — per round** | **2** (gen 6000 + critique 1200) | serial | gen prompt re-sends the pack **UNCACHED** (`llm/questions.py:28`) |
| **define — per round** | **2** (gen 6000 + critique 1200) | serial | gen is **cached** (`define/questions.py:32`) ✓ |
| **implement (per call)** | **N batches + judge**, ×2 iters | **serial** (`_BATCH_CONCURRENCY=1`) | gen is now **batched** (`_BATCH_UNITS=3` grounded units/call, `max_tokens=128000`); N ≈ units÷3 → cost scales with pack size (see quality plan) |
| **evaluate** | **0** — fully deterministic | n/a | not a latency concern |

Ranked wall-clock sinks:

1. **Implement assured loop** (`implement/assured/loop.py`) — **always-on** (the old `TPD_ASSURED` opt-in
   gate is gone), and generation is now **batched** (`generate/llm.py`): the pack's grounded units are split
   into `_BATCH_UNITS=3`-unit slices, one generation call each, run **sequentially** (`_BATCH_CONCURRENCY=1`).
   So one assured round = **N generation calls** (N ≈ units÷3) **+ 1 judge**, and the whole loop is that ×
   `TPD_ASSURED_MAX_ITERS` (2). For a big pack (e.g. LUZ-158230 ≈ 41 units → ~14 batches) that's **~28
   serial generations + 2 judges** under the 540s budget. By far the *Biggest LLM sink* — and it now
   **scales with pack size**, so **B1 (iters→1)** is the top turbo lever (halves the batch count).

   ⚠️ **The single biggest remaining implement-latency lever is BLOCKED: `_BATCH_CONCURRENCY`.** Batches are
   independent and *should* run concurrently (N serial → N÷k), but it's pinned to **1** because deployed logs
   showed concurrent batches failing — **concurrent in-process ADK Runners are the prime suspect**
   (`generate/llm.py` comment). This is the **same root cause that killed A3** (planners racing on shared ADK
   `ctx`), now confirmed in prod. Unblocking it (a safe concurrency model for ADK Runners) would cut implement
   wall-clock the most — but it's a real fix, not a flag flip. Until then, do **not** propose parallelizing
   any ADK-Runner path; prod evidence says it breaks.
2. **Gather codegraph build** — up to 300s git-clone + graphify (network/subprocess, not LLM).
3. **Refine/define interrogation** — 2 serial calls **per round** (generate + critique), × 3–4 rounds
   × up to 4 re-seed passes. Refine's generate is **uncached** (define's is cached).
4. **Per-round critique** (`INTERROGATION_CRITIQUE`, default **ON**, `interrogate/critique.py:19`) —
   doubles every interrogation round from 1 call to 2.
5. **Serial explore planners** (when explore on) — 2–3 independent calls run sequentially.
6. **AnthropicVertex client is re-constructed on every `complete()`** (`vertex.py:44`) — per-call
   auth/transport setup.

---

## Mode A — Fast (no quality loss). Unconditional.

Each item produces **identical model output**; only the plumbing changes.

### A1. Reuse the AnthropicVertex client
`common/llm/vertex.py:44,76` build a fresh `AnthropicVertex(project, region)` per call (credential +
httpx transport setup each time). Cache it.

```python
from functools import lru_cache

@lru_cache(maxsize=None)   # one (project, location) per process
def _client(project: str, location: str):
    from anthropic import AnthropicVertex
    return AnthropicVertex(project_id=project, region=location)
    # ponytail: process-wide singleton; anthropic client is safe to share across the to_thread workers.
```
Use it in `complete()` and `describe_image()`. **Effort: XS.** Win: removes N client inits per pipeline run.

### A2. Prompt-cache the refine rounds (the big one)
`common/llm/questions.py:28` calls `complete(question_prompt(pack, round_name), max_tokens=6000)` with
**no `cache_prefix`** — so the full pack is re-sent uncached across 3 rounds × up to 4 re-seed passes.
Define already solved this: `define/questions.py:31-32` passes `cache_prefix=pack_block(summary)` with
`include_context=False`. **Copy that split into the refine path:**

- Split `question_prompt(pack, round_name)` into a stable `pack_block(pack)` (cached prefix) + a
  round-only instruction (`include_context=False`), mirroring `common/testplan/llm/prompts.py:83`.
- Pass `cache_prefix=pack_block(pack)` into `complete(...)`.

Identical questions, cached input tokens → materially faster + cheaper on every round after the first.
**Effort: S.** Win: largest no-quality-loss cut on the refine path.

### A3. Parallelize the independent serial calls — ❌ DROPPED (unsafe, now prod-confirmed)
Investigated during implementation: `_run_planner` runs each planner under the **same** ADK `ctx` and
writes shared `ctx.session.state[output_key]` (`gather/agent.py`). `asyncio.gather`-ing them races on
that shared session state — not a safe free win. And both targets are low-value: the planners are 2–3 ×
400-tok (minor per the diagnosis), and steps-batching is off by default (`TPD_LLM_DETAIL`). Skipped.
**Now confirmed in prod:** the quality workstream tried concurrent scenario-generation batches and had to
pin `_BATCH_CONCURRENCY=1` because concurrent in-process ADK Runners failed live (`generate/llm.py`). So
"parallelize ADK calls" is not just skipped here — it's a **known-broken pattern**; the real win is fixing
ADK concurrency (see sink #1), not sprinkling `asyncio.gather`.
*Not* parallelizable either: assured gen→judge (judge grades the generation), interrogation rounds
(human answers between them).

**Mode A — implemented (✅ A1, ✅ A2; ❌ A3):** same outputs; cached client + cached refine rounds.
`63 passed` on the question/prompt/vertex/refine/interrogation tests.
- ✅ **A1** `common/llm/vertex.py` — `_client` lru_cache singleton, both call sites wired.
- ✅ **A2** `common/llm/questions.py` + `prompts.py` — refine rounds now pass `cache_prefix=pack.summary_text()`
  with `include_context=False` (mirrors define).

> Cut from an earlier draft: an ADK-cache "verify it hits" item (fold into Phase-0 — just read
> `cache_read` tokens) and a fail-fast request timeout (real, but it's *reliability*, not latency —
> route to a separate pass).

---

## Mode B — Turbo (small quality trade). One toggle.

You asked for **two** modes, so this is **one boolean**, not a profile enum. Mode A is unconditional
(always on); Mode B is a single `TESTAGENT_TURBO` flag on the pydantic `Config` (`common/adk/config.py`):

```python
turbo: bool = False   # env TESTAGENT_TURBO — flips the aggressive knobs below
```

When `turbo` is on, it sets the **defaults** for these already-existing env flags (an explicit env still
wins). No `perf.py` mapping layer — a handful of `os.environ.setdefault` at startup, or read `turbo`
directly at each gate. Turbo is mostly *wiring existing flags*, not new logic.

| Knob | Flag (exists?) | default | turbo | Quality trade |
|---|---|---|---|---|
| **B1** Assured iterations | `TPD_ASSURED_MAX_ITERS` ✓ | 2 | 1 | skips reflect→regenerate improvement pass |
| **B2** Per-round critique | `INTERROGATION_CRITIQUE` ✓ | on | **off** | loses round self-grading; halves each round (2→1 call) |
| **B3** Refine re-seed passes | `RefineSession(max_rounds=…)` arg (exists) | 4 | 1 | shallower re-seed exploration |
| **B4** Explore planners | `explore` (request flag) ✓ | as-asked | **skip** | no self-exploration enrichment |
| **B5** Fast model tier | **NEW** `VERTEX_MODEL_FAST` | off | on (judge/critique/distill/restate) | cheaper model on judging/summarizing sub-tasks |

**Cut B6 (lower max_tokens):** `max_tokens` is a *ceiling*, not a cost — a short answer streams the same
under any cap, so lowering it buys no speed. Worse, it's actively harmful: both `default_max_tokens` and
`_SCEN_MAX_TOKENS` are now **128000** (the claude-sonnet-5 output ceiling) precisely because a lower cap
*truncates* mid-JSON → schema-invalid → silent heuristic fallback (~0.08). The quality workstream even
concluded that raising the cap alone can't win (a full suite can exceed any single call) — hence
**batching**, not bigger caps. Caps go **up** when they bite, never down for speed.

**B3 wiring:** `max_rounds` is already a `RefineSession` constructor arg (default 4) — pass it from the
`turbo` flag; don't add a parallel module constant.

### B5 is the only real new feature: a second model tier — ✅ IMPLEMENTED
**Design decision:** the fast tier is **decoupled from turbo** — driven purely by the `VERTEX_MODEL_FAST`
env, not the `TESTAGENT_TURBO` flag. `tier="fast"` resolves to `VERTEX_MODEL_FAST` when set, else falls
back to the default model, so it's **inert until an operator configures a fast model** (zero behaviour
change by default, and usable independently of the other turbo trade-offs). `_tier_model` (in
`providers/vertex_claude.py`) dedups the resolution across `llm_agent_model` + `complete`.

Today `agent_model()` / `complete()` resolve one model (`providers/__init__.py` registers one provider).
Added a `tier` parameter routed to `VERTEX_MODEL_FAST` when set:

```python
def agent_model(*, max_tokens=None, tier="default"): ...   # tier="fast" → VERTEX_MODEL_FAST
def complete(prompt, *, max_tokens, cache_prefix=None, tier="default"): ...
```

Route the **cheap classification/judging** calls to `tier="fast"` (a smaller model, e.g. Claude Haiku):
- distill 200-tok (`llm/distill/claude.py:13`)
- understanding/restate 700-tok (`llm/understanding.py:22`, `define/plan.py:65`)
- interrogation critique 1200-tok (`interrogate/critique.py:47`)
- assured **judge** 1500-tok (`implement/assured/loop.py:93`)
- optionally question generation (`llm/questions.py`, `define/questions.py`)

Keep the **big model for scenario generation** (`claude_scenarios`, the quality-critical creative step).
**Effort: M** (provider tier + `VERTEX_MODEL_FAST` env in `services.tf`/tfvars). This is the lever that
"considerably boosts" perceived speed because it shrinks the *majority* of calls (judging/summarizing),
not the one creative call.

### Gather-specific (orthogonal to profiles)
The 300s codegraph build blocks the crawl. Not an LLM problem — **pre-build the graph to GCS** so the
crawl attaches a cached node instead of git-clone+graphify inline (see the existing note on
`graphify update <repo> --force`). Mode-B users on a repo ticket should pre-build, not build inline.

**Turbo net (illustrative, one ticket):** implement 4 calls → 2; each interrogation round 2 calls → 1;
refine passes 4 → 1; judging/summarizing calls on the fast tier. Roughly a **2–3× wall-clock cut** on the
LLM-bound stages, at the cost of one reflect pass, the self-critique signal, and shallower re-seed.

---

## Measurement — the "no quality loss" guardrail

**Update (commit 5603766):** the benchmark harness is now **built** — `Benchmark` model + `store` +
`compute_benchmark` + `compare_benchmarks`/`summarize_benchmarks`, computed on a gateway **on_finish
hook** per run, cache-aside through the new `common/cache` port (`CACHE_BACKEND`: null/memory/redis).
This makes Phase 0 almost free — the plumbing exists; it just doesn't time anything yet.

The only gap: `Benchmark` (`common/benchmark/model.py`) still records **only quality** (pqs/tps/
components/retrieval), **no latency**. So:

1. **Add one `latency_ms` field** to the `Benchmark` dataclass (+ bump `SCHEMA_VERSION` to invalidate
   old blobs) and stamp a whole-run `time.monotonic()` delta in the **existing gateway on_finish hook** —
   one field, one call site, no per-stage stamping until the total fingers a dominant stage.
2. **A/B the golden ticket.** Run **LUZ-156281** with `turbo` off vs on; read the deltas straight out of
   the existing `compare_benchmarks` / `summarize_benchmarks` tools (PQS/TPS + the new latency). Wire
   into `docs/PLAN-run-benchmark.md`.
3. **Gate.** "No quality loss" = Mode-A PQS/TPS within noise (±1 pt) of baseline. Turbo may drop quality
   but the drop must be *bounded and reported*, not silent.

> The new `common/cache` `Cache` port (Redis/Memorystore) caches **benchmark blobs**, not LLM responses.
> It *could* back an LLM-response cache, but hit rate is ~0 (per-ticket packs, sampled output) — prompt
> caching (A2) is the real lever. Reuse the port only if we later find a genuinely repeated exact call.

---

## Phasing

- **Phase 0 — Measure.** ✅ Done (full suite 536 passed). Chose **per-`ask()` accumulation** over a
  start-stamp: `BridgeSession.ask` (the choke point every gateway→agent call routes through) times each
  call and adds it to a per-run total via the bankless `get_cache()`; `compute_benchmark` reads it into
  the new `Benchmark.latency_ms` (`SCHEMA_VERSION` 1→2). This captures **pure server time** (excludes
  human think-time between gates). Caveat: gateway and `compute_benchmark` must **share a cache** —
  offline A/B = one InMemory (`CACHE_BACKEND=memory`); prod = point both at the same Redis. Default
  NullCache = no capture (`latency_ms=None`), never load-bearing.
- **Phase 1 — Mode A.** ✅ A1 client reuse + ✅ A2 refine caching done (63 passed). ❌ A3 dropped
  (planners share ADK `ctx` state → racy; low-value). Next: run the A/B on LUZ-156281 (turbo off vs on).
- **Phase 2 — Turbo toggle.** ✅ Done (80 blast-radius + 3 turbo tests pass). `turbo_on()` on `Config`
  read at the 3 gates: B1 assured iters→1 (`assured/loop.py`), B2 critique off (`interrogate/critique.py`),
  B3 refine passes→1 (`interrogate/loop.py::_resolve_max_rounds`). Explicit per-flag env still overrides.
  B4 (explore) needs no code — already default-off; turbo doesn't force-override an explicit `explore`
  request. **Follow-up:** add `TESTAGENT_TURBO` to `variables.tf`/`services.tf` so it's deploy-settable.
- **Phase 3 — Fast tier (B5).** ✅ Done (591 passed). Provider `tier` + `VERTEX_MODEL_FAST`, routed at
  distill/understanding/define-brief/critique/judge; scenario generation + question generation stay on
  the full model. Decoupled from turbo (env-driven, inert until `VERTEX_MODEL_FAST` set).
  **Follow-up:** add `VERTEX_MODEL_FAST` to `variables.tf`/`services.tf` + pick the fast model (e.g. Haiku).
- **Phase 4 — Tune.** Pick the default (turbo on or off?) + the fast model from Phase-0/3 benchmark data.

## Invariants to preserve
- Heuristic fallback stays intact — every LLM call already degrades to a heuristic on
  timeout/unconfigured; don't break that path.
- `evaluate_*` stays deterministic (0 LLM).
- Explicit env always overrides the profile default (profiles set *defaults*, not hard values).
- Scenario **generation** keeps the full model even in turbo (protect the creative step; shrink judging).
