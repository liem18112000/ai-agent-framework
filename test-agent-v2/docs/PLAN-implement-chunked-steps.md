# Chunked, Resumable `implement_plan` — one LLM unit per call

**Purpose.** `implement_plan` errors on the client *nearly every time*. It is **one synchronous MCP
call that blocks for the entire assured loop** (generate → judge → reflect → regenerate, ×N rounds)
before returning a single byte. That wall-clock routinely exceeds the client's MCP **tool idle
timeout**, so Claude Code aborts the call — even though the server keeps grinding and checkpoints
partial state the client never sees. The fix: turn `implement_plan` into a **resumable step
function** — one bounded LLM unit per call, returning `[state: in_progress]` until `[state: done]` —
reusing the GCS checkpoint/resume the assured loop *already* has and the multi-turn `[state: …]`
convention `define_plan` *already* uses. No new tool, no background-task infra.

> House style follows the sibling `PLAN-*.md`: TL;DR + root cause, timeout anatomy, the design, the
> client-drive contract, phased roadmap, invariants, test plan.

---

## 0. TL;DR

**Symptom.** `● implement_plan errored` on almost every ticket. Retrying sometimes "works" because
the loop is resumable and a prior aborted call already did a round.

**Root cause (not transient).** The MCP tool call is a single blocking request. The heavy assured
loop's worst-case wall-clock (≈540s budget; one round alone up to ~360s) sits **above the client's
~300s idle timeout**. The client gives up first; the server does not.

**Fix.** Bound the work *per call*, not per *whole loop*. Each `implement_plan(context_id)`
invocation runs **exactly one LLM unit** (one generate batch, or the judge), persists a cursor +
partial artifacts, and returns a machine-readable status. The client re-calls until done — the same
way it already drives `refine` and `define_plan`. One unit ≤ `TPD_GEN_TIMEOUT_S` (180s) « 300s.

**Second win (folded in).** Split the single 6000-token "generate ALL scenarios" call into **per-kind
batches**. Smaller/faster per call *and* it kills the known silent `max_tokens` truncation
(6000 tokens across happy+negative+boundary+error → truncated → silent heuristic fallback).

**One-shot mode stays.** The pipeline fn keeps a run-to-completion path (default) — the eval harness
and ~20 tests call `implement_plan(bank, ctx)` directly and expect a full `ImplementResult`. Chunking
is a budget the **MCP-facing agent** passes; it is not a rewrite of the loop.

---

## Status — SHIPPED (ponytail-refined), 2026-09-15

Built and green (514 passed / 14 skipped, ruff clean). The implementation deliberately **narrows** the
plan below to the smallest diff that fixes the reported failure (*implement_plan errors nearly always*):

- **Granularity = one assured ROUND per call, not one LLM unit.** The judge is cheap (`max_tokens=1500`),
  so one round ≈ one slow generate + one fast judge, comfortably under the ~300s idle ceiling. Round-level
  stepping **reuses the existing `assured.json` checkpoint** — so the plan's separate
  `implement-progress.json` cursor (§3.2) was **not built** (YAGNI). Env `TPD_IMPLEMENT_STEP_ROUNDS`
  (default 1) sets rounds-per-call; the pipeline arg is `max_rounds` (`None` = run-to-completion).
- **Best scenarios are written through each pause** (`store.write_scenarios` in the loop's resume path +
  the pipeline's pending branch) so a resume restores them and a lower-scoring later round can't displace
  a better earlier one — this also fixed a latent resume quirk (best set was lost across a kill).
- **Per-kind batching (§3.3 / Phase 1) DEFERRED.** It fixes *max_tokens truncation*, a quality problem,
  not the *timeout* reported here. It would also break the exact-call-count test contract
  (`fake.calls == 2/4`) and only cuts latency if generation runs concurrently (peak-memory/OOM risk).
  Revisit when a real plan truncates its scenario set, as its own change.

Files touched: `implement/assured/loop.py` (round budget + pending + resume restore),
`implement/generate/pipeline.py` (`max_rounds`, resume-aware test-data, pending branch),
`implement/generate/agent.py` (`_step_rounds`, `[state: …]` reply, capture-on-done),
`models/scenario.py` (`ImplementResult.done`), `bridge/mcp_server.py` + `gateway/mcp_server.py`
(multi-turn client contract), `tests/test_plan_assured.py` (2 stepping tests).

---

## 1. Timeout anatomy — the numbers that collide

| Layer | Knob | Default | Where |
|---|---|---|---|
| One generator LLM call | `TPD_GEN_TIMEOUT_S` | **180s** | `common/testplan/llm/adk.py` |
| Whole assured loop wall-clock | `TPD_ASSURED_BUDGET_S` | **540s** | `implement/assured/loop.py` |
| Assured rounds | `TPD_ASSURED_MAX_ITERS` | **2** | `implement/assured/loop.py` |
| A2A HTTP (gateway→agent) | `A2A_CLIENT_TIMEOUT` | **600s** | `common/bridge/a2a_client.py` |
| **MCP tool idle (client)** | `CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT` | **~300s** | Claude Code |

**The collision.** The server is provisioned to run up to ~540–600s. The **client** aborts at ~300s.
Every layer *below* the client is generously sized; the client is the one that fires. A single call
therefore has to finish in ~300s — but one assured round (generate ≤180 + judge ≤180) can already
blow past it, and the loop runs up to two rounds plus test-data/steps. The call cannot reliably fit,
so it "nearly always" errors.

**Why retry sometimes works.** `run_assured_scenarios` checkpoints `assured.json` after every round
and resumes (`read_assured_state` → `done_rounds`). An aborted call that completed round 1 leaves
state behind; the retry finishes round 2 fast enough to return. That is the accidental version of the
fix we are about to make deliberate.

---

## 2. Current flow (one blocking call)

```
implement_plan (MCP)                              [blocks up to ~540s]
  └─ session.ask("implement <ctx>")               A2A message/send, 600s http
       └─ TpdRouter → ImplementOrchestrator
            └─ ImplementAgent.generate
                 └─ implement_plan(pipeline)       one-shot, returns full ImplementResult
                      ├─ generate_test_data        (heuristic unless detail)
                      ├─ run_assured_scenarios ◄── HEAVY: for round in 1..MAX_ITERS:
                      │      claude_scenarios       1 LLM call (max_tokens=6000, ALL kinds)
                      │      judge                  1 LLM call
                      │      reflect → regenerate
                      ├─ generate_all_steps         (heuristic unless detail)
                      └─ finalize                   persist, feature, coverage, run log
```

Everything after `session.ask` returns **once**, at the very end. The client sees nothing until then.

---

## 3. Design — one LLM unit per call, cursor-driven

### 3.1 The unit ladder

A "unit" is **at most one `run_json_agent` call** (one Vertex round-trip, already bounded by
`TPD_GEN_TIMEOUT_S`). One MCP call executes one unit, persists, returns. Order:

| Unit | LLM? | Notes |
|---|---|---|
| `testdata` | only if `detail` | else heuristic, folded into `finalize` (instant) |
| `gen:happy` / `gen:negative` / `gen:boundary` / `gen:error` | **yes** (1 each) | per-kind scenario batch (§3.3) |
| `judge` | **yes** | critiques the union of this round's scenarios |
| *(reflect)* | no | if below-bar and rounds remain → reset gen cursor, loop |
| `steps[b]` | only if `detail` | one call per `_STEP_BATCH` (8) chunk |
| `finalize` | no | write scenarios/steps/feature/coverage + run log, mark `done` |

Each unit is ≤180s « 300s. A below-bar round costs `#kinds + 1` calls but each is its own short MCP
call, so total wall-clock is unbounded across calls yet **no single call risks the idle timeout**.

### 3.2 The cursor (extends the existing checkpoint)

`assured.json` already persists `iterations`/`reflections`/`accepted`. Add a sibling
`implement-progress.json` (or a `cursor` field on the assured state) — a tiny resumable pointer:

```jsonc
{
  "phase": "gen",              // testdata | gen | judge | steps | finalize | done
  "round": 1,                  // current assured round
  "gen_kinds_done": ["happy"], // per-kind batches completed this round
  "steps_batch": 0,            // next steps chunk index
  "detail": false
}
```

The step driver: `read cursor → run the one unit the cursor points at → advance cursor → persist →
return status`. Partial scenarios accumulate in the bank between calls (write-through per batch), so a
mid-flight crash resumes from the exact unit, not the round start. This is the same
best-effort-persist discipline the loop already uses.

### 3.3 Batched scenario generation (axis 2)

Today `claude_scenarios` asks for **every** scenario kind in one 6000-token call. On a rich plan the
model truncates at `max_tokens` and the whole call silently degrades to the heuristic (a known TPD
gotcha). Split it: one call **per kind** (`happy`, `negative`, `boundary`, `error`), prompt scoped to
that kind, its own smaller `max_tokens`. Benefits, both directly on the request:

- **Smaller/faster** per call — each fits the unit budget comfortably.
- **No truncation** — each kind gets its own token budget; a big happy set no longer starves the
  negatives.
- **Finer degrade** — one kind timing out degrades *only that kind* to heuristic, not the whole set.

The judge still runs **once** over the union; reflections still feed the next round's regeneration
(which re-runs the per-kind batches). `heuristic_scenarios` stays the per-kind fallback.

> Scope note (ponytail): batch **by kind** (≤4 calls), not per-requirement (unbounded). Kinds are a
> fixed, small set and already how scenarios are typed. Per-requirement chunking is speculative until
> a single kind on one plan proves too big — add it then.

### 3.4 One-shot mode stays (don't break tests/eval/autonomous)

The pipeline `implement_plan(bank, ctx, …)` keeps **run-to-completion as the default**. Chunking is a
budget the caller passes:

```python
# pipeline signature gains one optional arg; None = run to done (today's behavior)
async def implement_plan(bank, context_id, *, max_units: int | None = None, ...) -> ImplementResult:
    ...
    # when max_units is set, run at most that many LLM units then return a partial result
    # carrying cursor state (result.done = False) instead of finishing the pipeline.
```

- **MCP path** (`ImplementAgent.generate`): passes `max_units=1`. Returns `[state: in_progress]`
  until the cursor reaches `finalize`/`done`, then the normal summary.
- **Tests / eval harness / any direct caller**: no arg → `max_units=None` → full `ImplementResult` in
  one call, exactly as today. Zero test churn on the happy path.

`ImplementResult` gains a `done: bool` (default `True`) so the agent knows whether to emit
`in_progress` or the final summary.

### 3.5 Client-drive contract (reuse, don't invent)

`define_plan` already returns `f"[state: {res.state} …]"` and the client re-calls it each turn. Mirror
it. `implement_plan` returns:

```
[state: in_progress]  gen:negative done (round 1) — call implement_plan again to continue
...
[state: done]  Implement complete: 4 test-data, 11 scenarios (6 happy / 5 negative), 44 steps. …
```

The gateway MCP instructions already say *"YOU (the client) own the … gates"* and drive the pipeline.
Add one line to the `implement_plan` tool docstring + the gateway instructions: **"Multi-turn: if the
reply starts `[state: in_progress]`, call `implement_plan(context_id)` again (no new args) until
`[state: done]`, then `get_scenarios`."** No new MCP tool — `implement_plan` is its own *continue*
verb, idempotent on `context_id`, exactly like `refine`/`define_plan`.

**Rejected alternative — streaming heartbeats.** Reset the client idle timer via A2A progress frames.
Heavier (bridge uses non-streaming `message/send`; needs `message/stream` + client progress handling)
and fragile over remote HTTP on this client (cf. the elicitation-over-HTTP breakage). The step
function reuses existing resume + the existing multi-turn convention. Not doing streaming.

---

## 4. Phased roadmap

### Phase 0 — mitigation (today, config only, no deploy of code)
- Set `TPD_ASSURED_MAX_ITERS=1` (one round → one generate + one judge; halves worst case).
- Tighten `TPD_GEN_TIMEOUT_S` (e.g. 120) so a slow generate degrades before the idle ceiling.
- Client-side: raise `CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT` (e.g. 600s) for this MCP server.
- **Buys breathing room; does not fix truncation or guarantee fit.** Real fix is Phases 1–3.

### Phase 1 — batched scenario generation (§3.3)
- `claude_scenarios(..., kind=…)` → per-kind call; `run_assured_scenarios` calls it once per kind and
  unions. `scenarios_prompt` gains a `kind` filter; per-kind `max_tokens`.
- Judge + reflect unchanged (operate on the union).
- **Ships value alone**: shorter calls + no truncation, even before the step function lands.
- Files: `implement/generate/llm.py`, `implement/generate/scenarios.py`,
  `common/testplan/llm/prompts.py`, `implement/assured/loop.py`.

### Phase 2 — cursor + `max_units` in the pipeline (§3.1–3.2, 3.4)
- Add `implement-progress.json` read/write to `common/testplan/memory/writers.py`.
- Thread `max_units` through `implement_plan` (pipeline) and `run_assured_scenarios`; write-through
  partial scenarios per batch; return `ImplementResult(done=…)`.
- Files: `implement/generate/pipeline.py`, `implement/assured/loop.py`,
  `common/testplan/models/scenario.py` (add `done`), memory writers.

### Phase 3 — MCP-facing step + client contract (§3.5)
- `ImplementAgent.generate` passes `max_units=1`, emits `[state: in_progress|done]`.
- Update `implement_plan` docstring (`bridge/mcp_server.py`) + gateway MCP instructions with the
  re-call loop.
- Files: `implement/generate/agent.py`, `test_plan_definition/bridge/mcp_server.py`, gateway
  instructions.

> Phases 1 and 2/3 are independently shippable. If time-boxed, Phase 1 alone measurably cuts the
> failure rate; Phase 3 removes it.

---

## 5. Invariants preserved

- **Best-effort / never-raise.** Every unit still degrades to its heuristic on timeout/invalid output
  and never raises; a partial run still yields a non-empty scenario set for `get_scenarios`.
- **Resumability.** Already the contract; the cursor makes it *per-unit* instead of *per-round*.
- **Assured quality signal.** Judge, threshold, reflections, `AssuredReport`, and the `guidance=`
  re-steer are unchanged — the loop is *paced*, not weakened.
- **I3 note.** The always-on assured loop already traded away the 1-LLM-call default; chunking does
  not add LLM calls, it only splits and paces existing ones (per-kind generation is the same total
  work as one combined call, minus the truncation waste).
- **Offline tests.** `max_units=None` default keeps every direct-call test one-shot; the fake model
  path is unchanged.

---

## 6. Test plan

- **Unit — cursor.** Drive `implement_plan(..., max_units=1)` in a loop with a fake model; assert it
  reaches `done` in the expected number of calls and the final `ImplementResult` equals the one-shot
  result (same scenarios/steps/coverage). One `assert`-based check is enough.
- **Unit — batched gen.** Fake model returns per-kind payloads; assert the union has all kinds and a
  single kind's timeout degrades only that kind to heuristic (others stay LLM).
- **Unit — no truncation regression.** Assert each per-kind call is issued with its own
  `max_tokens` and the combined 6000-token single call is gone.
- **Resume.** Persist a mid-flight cursor, re-enter, assert it continues from the pending unit (not
  round start) and does not duplicate already-written scenarios.
- **Regression.** The existing `test_plan_assured.py` / `test_plan_implement.py` suites stay green
  unchanged (they exercise `max_units=None`).
- **Gateway.** `test_gateway.py`: an `in_progress` reply round-trips as `[state: in_progress]` and a
  follow-up call advances.

---

## 7. Ponytail ledger

- **No new MCP tool** — `implement_plan` re-called is the continue verb (like `define_plan`).
- **No background-task/queue infra, no streaming** — reuse the existing GCS checkpoint + multi-turn
  convention.
- **No rewrite of the loop** — `max_units` is a budget; the full loop is still the run-to-done impl.
- **Batch by kind, not per-requirement** — fixed small set; defer finer chunking until one kind
  actually overflows.
- **Cut for now:** a dedicated `implement_status` read tool (the `[state:]` line + `get_scenarios`
  already cover it); progress percentages (kinds are few — name the unit instead).
