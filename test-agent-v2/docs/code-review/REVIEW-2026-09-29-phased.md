# test-agent-v2 — code review, categorised and phased

**Date:** 2026-09-29 · **Branch:** `feature/test-agent/final-v2-release` · **HEAD at review:** `a08a3d1`
**Scope:** whole tree — `src/` (309 files, ~20.4k lines), `tests/`, `tools/`, `main.py`/`worker.py`/`redis_worker.py`,
and `deployments/test-agent-v2/*.sh`
**Passes:** max-effort correctness · security · ponytail (over-engineering + comment noise) ·
ruff extended (`ARG,ERA,SIM,RET,C4,PIE,PERF,B,UP,S`) · cross-file duplication scan · comment-density analysis
**Baseline:** 780 passed / 16 skipped. **After the phases applied here:** 784 passed / 16 skipped, ruff clean.
**Prior reviews reconciled:** `REVIEW-2026-09-25-prioritised.md`, `REVIEW-final-v2-release-phased.md`,
`REVIEW-test-executor-phased.md`, `REVIEW-MASTER-phased.md` — findings already resolved there are not repeated.

---

## Headline

Three things are worth your attention, and the rest of this document exists mostly to tell you what
*isn't* worth changing.

1. **A live-credential file is one `git add -A` away from being committed.** Not a code defect — a
   `.gitignore` gap opened by the new rotation script. Highest severity here, cheapest fix.
2. **The token accounting added in `a08a3d1` reports 2–4× the real bill.** Reproduced, root-caused,
   fixed, regression-tested. It is the only genuine logic bug the pass found.
3. **There is no comment-noise problem and no bloat problem.** A restating-comment detector over all
   309 source files returned **two** candidates and both were false positives. The prose/code ratio is
   0.20 and the long comment blocks are load-bearing provider/infra explanations. The requested
   "remove nonsense comments" work has essentially nothing to act on, and saying so is more useful
   than manufacturing a cleanup.

The shortening that *was* available came from duplication, not from verbosity: 62 lines of copy-pasted
package bootstrap, 25 lines of hand-rolled numeric-env parsing that a shared helper already covers.

---

## Categories at a glance

| Category | Count | Net verdict |
|---|---|---|
| **A. Security** | 1 | One P0, fixed |
| **B. Correctness** | 3 | One P1 (repro'd, fixed) and two P2, all fixed |
| **C. Cost / performance** | 1 | Latent, conditional — documented, deliberately not built |
| **D. Ponytail — shorter code** | 4 | all 4 applied (−87 lines + 2 stores de-duplicated) |
| **E. Hygiene** | 1 | Applied |
| **F. Verified non-findings** | 6 classes | **Do not "fix" these** |
| **G. Architectural decisions** | 2 | Yours to make, not refactors |

---

## A. Security

### SEC-1 · **P0** · Live credentials sit in a non-ignored file — `.env.bak`

**Where:** `deployments/test-agent-v2/rotate_a2a_bearer_key.sh:95` (`cp "$ENV_FILE" "$ENV_FILE.bak"`),
root `.gitignore`

The new rotation script backs `.env` up to `test-agent-v2/.env.bak` before rewriting it. Root
`.gitignore` covers `.env` but **not** `.env.bak`, so the backup is an untracked, committable file —
and `git status` currently lists it.

Its contents are not just the superseded bearer tokens. The script rotates only
`GATEWAY_BEARER_TOKEN` and `A2A_BEARER_TOKEN`; everything else in the file is copied across **still
live**:

| Key in `.env.bak` | Rotated by the script? |
|---|---|
| `ATLASSIAN_API_TOKEN` | no — **live** |
| `ATLASSIAN_BITBUCKET_APP_PASSWORD` | no — **live** |
| `TYPESAFE_API_KEY` | no — **live** |
| `KGA_BRIDGE_BEARER_TOKEN` / `TPD_BRIDGE_BEARER_TOKEN` | no — **live** |
| `GATEWAY_BEARER_TOKEN` | yes (superseded) |

A single `git add -A && git commit` publishes four live credentials into history.

**Fixed (Phase 0):** `.env.bak` and `.env.*.bak` added to root `.gitignore`. Verified with
`git check-ignore -v test-agent-v2/.env.bak`.

**Still on you:** delete the existing `test-agent-v2/.env.bak` once you have confirmed the rotation
completed and you no longer need the rollback copy. I did not delete it — it is a credentials file
and removing it is your call, not mine.

---

## B. Correctness

### TOK-1 · **P1** · Token accounting reports 2–4× the real spend

**Where:** `src/common/admin/tokens.py:persist_usage` × `src/common/llm/meter.py`
**Introduced by:** `a08a3d1` (the F5 token-accounting feature) — i.e. brand-new, never reviewed

The meter's counters are **process-cumulative**: `_TOTALS[run_id][label]` only ever grows, and
nothing clears it. `persist_usage` folds `meter.snapshot(run_id)` into the stored blob and
**accumulates** rather than overwrites. Both halves are individually correct and together they
double-count, because an implement run is chunked and `_persist_tokens` fires on *every* chunk
(`pipeline.py:130` on a pause, `pipeline.py:165` at the end) — and consecutive chunks of one run share
a warm Cloud Run instance, so the counters are *not* empty on chunk 2.

Stored total after *n* chunks is the triangular sum, not the sum. The admin view is worse: `_collect`
adds `meter.snapshot(rid)` on top of the stored blob that already contains it.

**Reproduced** (3 chunks, one process, 100 input tokens each):

```
truth      : input=300 output=30 calls=3
stored     : input=600 output=60 calls=6     <- 2x
admin view : input=900 output=90 calls=9     <- 3x
```

A real 5-chunk implement stores 3× and displays 4×. The **ratios** stay correct, which is exactly why
this reads as plausible — `summary_line`'s cache-hit percentage is right while every absolute number
is wrong. A feature whose whole purpose is answering "what did this cost?" was answering it wrongly.

The existing test missed it because it calls `meter.reset()` between chunks with the comment
`# a new Cloud Run instance picks up the run` — it covers only the cold-instance case, which is the
*uncommon* one.

**Fixed (Phase 1):** `meter.snapshot(..., drain=True)` — snapshot-and-clear under the existing lock,
so the caller owns what it persisted. `persist_usage` is the one caller. Same change also bounds
`_TOTALS`, which previously grew for the life of the process (one entry per run, forever).

**Regression test:** `tests/test_admin_tokens.py::test_persist_does_not_double_count_chunks_on_one_warm_instance`
— three chunks, no reset, asserts 300/30/3 in storage, in the admin view, and an empty meter after.

### TOK-3 · **P2** · The token admin surface is unreachable from the gateway

**Where:** `src/admin_agent/agent.py:47-50` (registered) vs `src/admin_agent/bridge/mcp_server.py` (not)

`a08a3d1` added four commands to `AdminRouter` — `token-usage`, `token-agents`, `token-estimate`,
`token-lesson` — and registered none of them on the admin MCP bridge. That bridge is what the single
MCP gateway exposes, and the gateway is the only client-facing surface: the agents are A2A-only.

So the entire F5 operator surface is reachable only by speaking A2A to the admin agent directly with
`A2A_BEARER_TOKEN`. The feature works; nobody can call it the documented way.

Found while building the post-deploy check, which needs `token-usage`.

**Fixed (Phase 5):** four forwarders in the style of the existing ones — and, more usefully, a guard
so the next verb cannot slip the same way. `test_gateway.py::test_every_admin_verb_is_reachable_over_mcp`
enumerates `AdminRouter._commands()` and fails on any verb with no MCP tool. Mutation-checked: with
the forwarders reverted it names exactly the four token verbs.

The `AdminRouter` docstring said adding a verb was "a new method plus one line here", which is the
trap that produced this; it now says the forwarder is part of the job. Also completed the dict
`register_tools` returns — the six `prompt_*` tools and `forget_memory` were registered on MCP but
missing from it, so they were callable over the wire yet not importable from `gateway.mcp_server`,
which is how the tests reach them.

### PROXY-1 · **P2** · A failed `claude` CLI call returns `200 OK` with an empty completion

**Where:** `src/claude_proxy/server.py:38`

`subprocess.run(..., check=False)` and only `.stdout` is read. When the CLI fails — not logged in,
quota exhausted, crash — stdout is empty, `json.loads("")` raises, the handler falls through to
`return out` (`""`), and `do_POST` wraps that empty string in a **200 chat-completion**. litellm sees a
valid empty response, so the generator degrades to its heuristic path *silently*. Every diagnostic
signal (`stderr`, the exit code) was discarded.

Local/compose-only path (`TESTAGENT_MODEL_BACKEND=litellm`), which is why it is P2 rather than P1.

**Fixed (Phase 2):** check `returncode`, raise with the truncated `stderr`; the existing
`except Exception` turns it into the 500 the client can actually read.

---

## C. Cost / performance

### CACHE-1 · **P3 — documented, deliberately NOT built** · The fast tier silently defeats prompt caching

**Where:** `src/common/llm/understanding.py:claude_understanding` (`tier="fast"` + `cache_prefix`),
`src/test_plan_definition/define/plan.py:make_restater` (same shape)

Anthropic prompt caches are **per model**. `claude_questions` runs on the default tier;
`claude_understanding` passes `tier="fast"` with the byte-identical `pack.summary_text()` prefix. The
code comment states the two "share one cached prefix" — that holds only while both resolve to the
same model.

`VertexClaudeProvider._tier_model` maps `fast` → `VERTEX_MODEL_FAST` **when set**. That variable
appears in no `.env`, no `.tf`, and no compose file, so today fast == default and the optimisation
works as written.

The moment an operator sets `VERTEX_MODEL_FAST`, `refine.understanding` and `define.brief` become
one-call-per-pass stages writing a 1h cache entry at **2× input price** that nothing in that pass can
read. Within a 1h TTL a second pass recovers it; a single-pass context pays a net increase.

**Deliberately not fixed.** A guard for a configuration nobody has set is speculative complexity. The
one-line fix, if you ever set that env: pass `cache_prefix=None` when the resolved tier model differs
from the default — or simply route those two stages through the default tier.

---

## D. Ponytail — shorter code

### PONY-1 · **applied** · Package bootstrap copy-pasted into three `__init__.py` (−35 lines)

The 12-line dotenv → `GOOGLE_GENAI_USE_VERTEXAI` → ADC-project sequence was byte-identical in
`knowledge_gathering`, `test_plan_definition` and `test_evaluation`. One copy drifting is a per-agent
behaviour difference nobody would think to look for.

New `src/common/bootstrap.py` with `bootstrap_adk()`; the three inits go 21/21/20 → 9 lines each.

**Why not `common/env.py`** (the obvious home): it has a module-level `get_logger("common.env")`, and
`common.monitoring` configures its toggle from the environment on the **first** `get_logger` call.
Importing it ahead of `load_dotenv()` would freeze every `*_LOG` toggle at its pre-`.env` value. The
new module imports stdlib + dotenv only, and the docstring says why so nobody "tidies" it later.

### PONY-2 · **applied** · Five hand-rolled numeric-env readers the shared helper already covers (−20 lines)

`3d2448c` introduced `common.env.env_int`/`env_float` and `cd1bac3` claimed to finish the conversion.
Five sites were still hand-rolling it:

| Site | Now |
|---|---|
| `adk/providers/vertex_claude.py:_fast_max_tokens` | `max(1, env_int(...))` |
| `interrogate/loop.py:_resolve_max_questions` | `max(1, env_int(...))` |
| `testplan/llm/adk.py:_gen_timeout_s` | `max(1.0, env_float(...))` |
| `test_plan_definition/implement/generate/agent.py:_step_rounds` | `max(1, env_int(...))` |
| `knowledge_gathering/gather/explore/source_gate.py:_f` | **deleted** — a verbatim re-implementation of `env_float` |

Not just shorter: the hand-rolled versions swallow a bad value without logging it, which is the one
thing `env.py` exists to do.

### PONY-3 · **applied** · `_ensure()` duplicated between two SQL stores

`common/memory/pg/store.py:_ensure` and `test_executor/store/sql.py:_ensure` were byte-identical: the
double-checked lazy schema-apply plus an identical `__init__`, down to the `# no await before
assignment → safe under cooperative asyncio` comment. The race it guards (MEM-02, `tuple concurrently
updated`, which degrades recall *silently*) is subtle enough that two copies is a real hazard — a
correction landing in one is invisible in the other.

Now `common.db.SchemaOnce`: a base class holding `__init__` + `_ensure`, with each store declaring its
own `SCHEMA_SQL`. `PgMemoryStore(SchemaOnce)` and `ExecStore(SchemaOnce)` each lost 22 lines of body.
Two real implementations, not one — this is de-duplication, not a speculative abstraction.

**What the refactor uncovered:** `_ensure` had **no offline coverage at all**. The only caller was
`tests/test_pg_integration.py:44`, which skips without a live pgvector — so the race fix was untested,
twice over. Three tests added in `tests/test_db.py` against a fake engine that yields the event loop
inside `begin()` (without that await the race cannot be reproduced):

- every statement applied exactly once across repeated `_ensure()` calls
- five concurrent first callers produce **one** `begin()` — mutation-checked: deleting the `async with
  self._lock` makes it fail with 5, and restoring it passes
- each subclass applies its own DDL (the refactor's real risk: one store inheriting the other's schema)

Also dropped: `SCHEMA_SQL` re-exported from `test_executor/store/__init__.py` with zero consumers.

### PONY-4 · **applied** · `tools/` was outside every lint gate

`ruff check .` reported 22 findings, **all** in `tools/` — the directory no prior review or CI
invocation covered. 17 auto-fixed (stale `# noqa: E402`, import sorting, `RUF010`). The 5 remaining
(`TRY004`, `SIM117`, `ISC004` ×3) are style-only in rules this project does not select; I read all
three `ISC004` sites specifically because implicit concatenation in a collection usually means a
missing comma — these are intentional line continuations inside tuples, not a bug.

---

## E. Hygiene

Covered by PONY-4 above: `src/` and `tests/` were already ruff-clean and remain so; `tools/` now is
too, modulo the five non-selected style rules.

---

## F. Verified non-findings — **do not "fix" these**

Each was investigated rather than pattern-matched. Listing them is the point: the next reviewer will
hit the same flags.

| Flag | Count | Verdict |
|---|---|---|
| `S608` SQL injection | 7 | **False positive.** Table names come from the DB catalog (`_table_names`) or a hard-coded allowlist; every value is a bound parameter. `_scope_type_where` interpolates only static column predicates. |
| `S101` assert | 1783 | Tests. |
| `ARG00x` unused argument | 358 | Protocol/callback conformance, as `REVIEW-2026-09-25` established. Deleting them breaks interfaces; the project selects neither `ARG` nor `RET`. |
| `PERF401` manual append | 8 | **Leave.** The loop bodies are multi-line constructor calls; an `extend(... for ...)` rewrite is longer to read for no measurable gain. The worthwhile ones were already done. |
| `B905` `zip()` without `strict=` | 4 | Three are provably equal-length (an explicit `len()` guard directly above, or `asyncio.gather` output). The fourth, `vector_memory._cosine`, truncates on a dimension mismatch instead of raising — cosmetic, and dims are enforced at the store. |
| `RET503` / `ERA001` | 2 | Both false positives, as previously assessed: the retry loop is total, and the "commented-out code" is prose ending in `TPD_ADK_CACHE=0.` |

Also swept and clean:

- **Silently-swallowing broad excepts: 0.** Every `except Exception` logs, re-raises, or carries a
  `# noqa: BLE001` with a stated reason.
- **Blocking I/O inside `async def`: 0.** The repeated historical defect class (serial Vertex calls,
  sync GCS on the loop) is genuinely closed — the new pre-crawl and implement paths are `to_thread`'d.
- **`_PREP` cache in `test_executor/runners/suite.py`:** I checked whether `_evict_expired` was dead.
  It is called (`suite.py:433`), and finished runs pop their own key — no leak.

### Comment quality — the requested cleanup has nothing to act on

A detector run over all 309 `src` files, flagging standalone `#` comments whose words substantially
repeat the following line of code, returned **2 candidates — both false positives** (markdown headings
inside a memory-bank template). Supporting measurements:

- prose/code ratio across `src` files over 40 lines: **0.20**
- comment blocks of 6+ lines: **9 blocks, 78 lines total** — read individually; each explains
  non-obvious external behaviour (litellm's `control` default silently selecting a 5-minute TTL; ADK's
  `_cache_control_injection_points` marking the last message; the `TRUNCATE` without `CASCADE`
  rationale). Deleting these re-opens the bugs they document.

The honest finding is that this codebase's comments are already the "why, not what" kind. No
comment-removal pass was performed because performing one would have removed information.

---

## G. Architectural decisions — decide, do not refactor

| id | Finding | Recommendation |
|---|---|---|
| A-3 | `Insight` (`common/models/refine.py`) and `PlanInsight` (`common/testplan/models/plan.py`) share 13 identical fields, then diverge — `Insight` has `origin_step`/`scope`/`status`, `PlanInsight` has `round`/`chosen`. | **Keep both.** A shared base for two dataclasses that have already diverged on both sides buys one struct and costs a coupling between the refine and plan packages. Revisit only if a third appears. |
| A-4 | `rotate_a2a_bearer_key.sh` writes its rollback backup **inside the repo**. SEC-1's `.gitignore` fix closes the commit path, not the "plaintext live credentials on disk indefinitely" one. | Consider writing the backup outside the working tree, or deleting it on successful completion. Your operational call — a rollback copy is a legitimate thing to want. |

---

## Phases

| Phase | Contents | Risk | Status |
|---|---|---|---|
| **0 — Safety + mechanical** | SEC-1 `.gitignore`; PONY-4 `tools/` lint; PONY-2 env readers; PONY-1 bootstrap collapse | none — no behaviour change | ✅ applied |
| **1 — The bug** | TOK-1 `drain=True` + regression test | low — one call site, covered by a test that fails without it | ✅ applied |
| **2 — Failure visibility** | PROXY-1 non-zero exit → 500 | low — local/compose path only | ✅ applied |
| **3 — Structural** | PONY-3 shared `_ensure` → `common.db.SchemaOnce` + the 3 tests it was missing | low — mutation-checked | ✅ applied |
| **5 — Reachability** | TOK-3 four admin forwarders + the router/bridge drift guard | low — additive | ✅ applied |
| **4 — Decisions, no code** | CACHE-1 (if `VERTEX_MODEL_FAST` is ever set); A-3; A-4; delete `.env.bak` | — | ⬜ yours |

### Phase order rationale

Phase 0 is first because SEC-1 is the only finding where *waiting* has a cost — a credentials file is
committable right now. Phase 1 follows because it is the only behaviour change worth making, and it is
guarded by a test that fails against the old code. Phase 2 is separated from Phase 1 only because it
touches a different deployment path (compose, not Cloud Run) and can ship or revert independently.
Phase 3 was deliberately last among the code changes: a pure de-duplication of two copies that are
both currently *correct* carries risk without carrying a fix. It earned its place once the missing
test coverage surfaced — collapsing the copies turned "one untested race fix per store" into "one
race fix, mutation-checked". Phase 4 is not work — it is four
questions that need your answer, not my guess.

### Verification

```
ruff check src/ tests/     -> All checks passed!   (tools/ has 5 style-only hits in non-selected rules)
pytest -q                  -> 784 passed, 16 skipped   (baseline 780/16; +1 TOK-1 regression, +3 SchemaOnce)
```

Applied diff across all four phases: **20 files**. Net source lines are roughly flat — ~150 lines of
duplication were deleted and the replacements (`common/bootstrap.py`, `common.db.SchemaOnce`) plus
four new tests cost about the same. That is the honest accounting: the win here is *one* copy of each
thing, with a test on the one that had none, not a smaller line count.
