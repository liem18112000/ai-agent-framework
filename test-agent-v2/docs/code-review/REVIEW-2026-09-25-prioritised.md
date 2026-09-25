# test-agent-v2 — review findings, prioritised and phased

**Date:** 2026-09-25 · **Scope:** `test-agent-v2/src` (20 398 lines, 309 files) + tests (11 581 lines)
**Passes:** ponytail-review (over-engineering) · targeted performance · targeted security · ruff extended
(`ARG,ERA,SIM,RET,C4,PIE,PERF`) · a deep `/code-review max` pass (**merged below**)
**Baseline:** 757 passed, 16 skipped, ruff clean. **Final:** 762 passed, 16 skipped, ruff clean.

Ordered by **value ÷ risk**, then grouped into phases that can each ship independently and stay green.

---

## Headline

The codebase is **not bloated** — 40 ruff findings across 20k lines, and **almost all of them are
contract-mandated false positives** (18 of the 19 unused-argument hits alone). There is **one genuine
performance defect** (P1), exactly **one** genuinely dead parameter, and two deliberate architectural
bets worth a decision rather than a change.

The sting is in the tail: fixing P1 **introduced a credential-misdirection bug** that the max-effort pass
caught and my own test could not. That is recorded in full under P0-1 — it is the most useful thing in
this document.

---

## P1 — Performance: `run_suite` repeats all per-run prep on every chunk poll

**File:** `src/test_executor/runners/suite.py` (the `run_suite` prologue)

A chunked run is polled: the client re-invokes `run_suite` until `[state: done]`. Every one of those
polls currently redoes the *whole* preparation, none of which changes between chunks:

| Repeated per poll | Cost |
|---|---|
| `load_scenarios(context_id)` | GCS read of `scenarios.json` |
| `_resolve_upload_refs(...)` | GCS read of `test-data.json` + base64 decode — **151 KB** for the transfer.zip set |
| `authenticate(...)` | for `bearer_fetch`, an **HTTP POST** that mints a fresh token |
| `fetch_spec(...)` | **HTTP GET of the spec — 48 KB** for `luz_docs` |
| `_persist_spec(...)` | GCS read + compare (write skipped when unchanged) |
| `_fetch_version(...)` | HTTP GET |

At the default `EXEC_CHUNK=5`, a 50-scenario suite = **10 polls** = 10× everything above: ~480 KB of spec
re-fetched, 10 token mints, ~1.5 MB of fixture base64 re-decoded, 30 GCS round-trips. The existing
`# ponytail:` note on the auth line ("a bearer_fetch re-fetches each poll — fine at chunk cadence") is
true in isolation but understates the aggregate: it is *six* repeated operations, not one.

**Fix as shipped:** memoise only the **expensive, non-secret** prep (the OpenAPI spec and the build
version) for the life of the run, keyed on `(run_id, base_url)`. Credentials are deliberately **not**
cached — see P0-2 below; the first cut of this fix did cache them and that was a security bug.

**Impact:** removes the repeated spec fetch, spec-cache read and version fetch — the bulk of a chunked
run's prep I/O. **Risk:** this looked like "pure caching, no behaviour change" and was not. See P0-1.

---

## P2 — Real dead code and small correctness tidy-ups

| id | File | Finding | Fix |
|---|---|---|---|
| C-1 | `test_executor/oracle/openapi.py:59` | `_response_schema(op, status, spec)` never uses `spec`; one caller | drop the parameter |
| C-2 | `common/llm/vertex.py:45` | `RET503` implicit `None` | ❌ **false positive** — the retry loop is total (returns, raises, or continues; the last attempt always re-raises), so the fallthrough is unreachable. No change. |
| C-3 | 9 sites | `PERF401` manual append-loops | `list.extend(...)` — shorter *and* faster |
| C-4 | `test_plan_definition/.../workers.py:88` | `SIM105` try/except/pass | `contextlib.suppress` |
| C-5 | `admin_agent/agent.py:114,146` | two handlers ignore their `rest` argument | ❌ **false positive** — registry-dispatched as `entry[0](rest)`; every handler must accept it. |
| C-6 | `implement/assured/loop.py:67` | `_decision_gate(plan, ...)` never reads `plan`; one internal caller | ✅ dropped. **The others first listed here were false positives**: `adk_metrics` (×4) is an ADK callback signature, `technical.py` is one of 10 `build_<round>(pack, primary, title, q)` siblings, `memory_view` is global-by-design. |

**Every item in this table was investigated before being changed, and three of the six turned out to be
false positives.** That ratio is the finding: reading the code first is what kept the "fixes" from
breaking interfaces.

---

## P3 — Interface-conformance false positives (do NOT delete)

**18 of the 19** `ARG` hits are **required by a contract** and deleting them would break it. They are
noise, not debt:

`ObjectStore.put(..., content_type)` in `store/local.py` + `store/memory.py` · `NodeFetcher.fetch(..., scope,
client, ident)` across 6 `gather/crawl/fetch/*.py` · `RunnerEngine.run(..., spec, path_vars)` in
`engines/browser.py` (already documented "API-only; browser ignores it") · `Embedder.embed(..., task)` in
`embed/ollama.py` · `HTMLParser.handle_starttag(..., attrs)` · `Cache` Protocol stubs.

…plus the ADK `EvalMetric` callback signature (×4), registry-dispatched router handlers, and the
10-member `build_<round>(pack, primary, title, q)` family.

**Action: NONE.** The project's ruff config selects neither `ARG` nor `RET`/`PERF`, so nothing is
failing — there is nothing to silence. Adding `noqa`s would be adding code for no benefit, and
underscore-prefixing a Protocol implementation's parameter risks breaking keyword calls.
**Do not "clean" these away.**

---

## P4 — Architectural bets: decide, don't refactor

| id | Finding | Recommendation |
|---|---|---|
| A-1 | `common/cloud/` is 445 lines with **one** implementation (`GcpCloudProvider`); `provider.py` is a 68-line Protocol for it | **Keep.** The KGA cloud tiers use it and azure/aws are on the roadmap. Revisit only if the second provider never arrives. |
| A-2 | `common/store/s3.py` (129 lines + a test) is **never selected** by any deployment config | **Keep the port, question S3.** `ObjectStore` has 4 implementations (gcs/local/memory/s3) so the *abstraction* is earned; S3 itself is speculative for a GCP-only deployment. Cheap to keep, so only cut it if it starts costing maintenance. |

Flagging both as **deliberate**, not as defects — the ponytail rule is "abstraction with one
implementation", and only A-1 meets it.

---

## Security — no findings

Swept deliberately: no secret values reach logs (only env-var *names*, lengths, and
`render_as_string(hide_password=True)`); 5 outbound call sites against 11 files carrying an egress guard;
`path_vars` originate in trusted env config, never in scenario text. The guards added earlier this session
(egress allow-list, response-size caps, remote-`$ref` blocking, upload-path exfil guard, 401/403-never-pass)
are all in place.

---

## Phases

| Phase | Contents | Risk | Why this order |
|---|---|---|---|
| **0** | C-1, C-3, C-4 + the numeric-env reader | none | Safe warm-up |
| **1** | **P1** — per-run prep memoisation | *thought* low, **was not** | Introduced P0-1; see below |
| **P0** | resume target/credential fix + cache hardening | — | Pre-empted the rest once the deep pass returned |
| **2** | C-6 — the one real dead param | low | Three of six turned out to be false positives |
| **3** | P3 | — | **Cancelled.** Not enforced; would be noise |
| **—** | A-1, A-2 | — | **No action.** Recorded as decisions. |

Each phase ended with the full suite green and ruff clean (`757` at baseline → **`762`** now).

---

## MERGED — deep `/code-review max` pass (returned; re-prioritised)

The max-effort pass reviewed the tree *including Phase 1*, and found **four real defects in the Phase 1
commit itself**, one of them a P0 that pre-empted the remaining phases. All are now fixed in `58dd76c`.

### P0-1 — a resume poll leaked the env's bearer to a different host ✅ fixed

The documented resume is `run_suite(context_id)` with **no env**. On chunks 2+ that gave
`resolve_env("") -> {}`, so `base_url` fell back to **`EXEC_BASE_URL`** — a different host
(`https://httpbin.org` in the deployed tfvars) — and `auth_cfg` was lost.

Before the Phase 1 cache that was merely *wrong target, no token*. **With** the cache, `_prepare_run`
returned chunk 1's `AuthContext`, so the tail of a run would have carried the **Luz dev bearer to
httpbin.org**, while `signals.target` still claimed the original env.

Root fix: when `env` is absent, recover the run's own env **name** from its ledger row — which also
repairs the pre-existing wrong-target half. The regression test now polls without the env (the shape the
router actually produces) and asserts every request stayed on the run's own `base_url`; verified it fails
with the recovery disabled.

### P0-2 … P0-4 — cache hardening ✅ fixed
| # | Finding | Fix |
|---|---|---|
| 2 | `_PREP_TTL_S = 600` is unrelated to a bearer's real lifetime → an expired token replayed for a run's tail | **credentials are no longer cached at all**; only the spec + build version (expensive, non-secret) are |
| 3 | Cache stampede — concurrent polls all miss and all fetch | `asyncio.Lock` per key + double-check |
| 4 | Overflow did `_PREP.clear()`, wiping *every* in-flight run → thundering herd | evict **expired** entries only |
| 5 | Entry popped only on the completion path → an abandoned run held a bearer for 600 s | moot: no credential is cached |
| 6 | The Phase 1 test re-passed `env` on every poll, so it could not catch P0-1 | polls 2-3 now omit it |
| 7 | `AuthCtx.headers: dict = {}` — one mutable dict shared across the session | `MappingProxyType` (already fixed before the pass returned) |
| 8 | Dead `try/except` left by my `env_float` conversion — `common/env.py` already swallows it | collapsed to one line |

### Diagram findings ✅ fixed (`f6086f8`)

Each was re-verified before acting — I diffed every element semantically against `HEAD` rather than
trusting the report, because reverting a diagram destroys work if the call is wrong.

| Finding | Verified | Action |
|---|---|---|
| `full-flow`, `exec-overview`, `exec-jev-cascade`, `openrig-refocus-flow` are pure re-serialisation churn | **0 semantic diffs** in all four — identical ids, text, colours, geometry, bindings | reverted |
| `gridSize 20 -> null` regression | confirmed on 3 of the 4 | restored with the revert |
| `full-flow` bbox shift desyncs its committed PNG | confirmed | moot after revert |
| `agents-swimlane-detail` arrows recoloured to `#c2410c` | confirmed — the *only* two arrows in that colour, and it is the User lane's identity colour | `sx_a950013 -> #1e40af` (solid=tool call), `sx_a950034 -> #64748b` (dashed=reply); PNG re-rendered and viewed |
| `agents-swimlane-detail-caveman.md` has no EXECUTE band | confirmed — doc predates the band | band ⑦ added, legend + takeaway updated |

**Not reverted, deliberately:** the rest of `agents-swimlane-detail` is a real improvement — it fixes a
genuine `HEAD` defect (six lane dividers had `height=1866` but `points` ending at `1656`, rendering
~200px short) and normalises the band's font sizes. The label recolours to `#64748b` were also kept:
grey is the dominant text convention in that file (24 of 56), so they conform rather than regress.

---

## Corrections to my own first pass

Investigating before changing overturned three of my findings. Recording them so the next reader does not
re-raise them:

- **C-2 (`vertex.py` implicit return) — FALSE POSITIVE.** `_with_retry` either returns, raises, or sleeps
  and continues; on the final attempt the guard always re-raises, so the implicit `return None` is
  unreachable. Ruff cannot prove the loop is total. No change.
- **C-5 (`admin_agent` handlers ignoring `rest`) — FALSE POSITIVE.** They are registry-dispatched as
  `entry[0](rest)`; every handler must accept it. Interface conformance, same as P3.
- **P3 was overstated, and is now NO ACTION.** 18 of the 19 `ARG` hits are mandated by a contract —
  Protocol, ABC, an ADK `EvalMetric` callback signature, registry dispatch, or the 10-member
  `build_<round>(pack, primary, title, q)` family. Exactly **one** was genuinely dead
  (`_decision_gate(plan, ...)`, dropped). And the project's ruff config does not select `ARG` at all, so
  there is nothing failing to silence — adding `noqa`s would be adding code for no benefit.

The wider lesson: **unused-argument linting is nearly all noise on a codebase built around protocols and
uniform dispatch.** It is worth running once to find the one real hit, not worth enforcing.

---

## Final status

| Phase | Status |
|---|---|
| 0 — mechanical shrink + the env-reader | ✅ `d6f5f0d` |
| 1 — per-run prep memoisation | ✅ `0fb0009`, hardened by `58dd76c` |
| P0 — resume target/credential fix + cache hardening | ✅ `58dd76c` |
| 2 — dead params | ✅ one real hit dropped; the rest were false positives |
| 3 — silence interface args | ❌ **no action** (not enforced; would be noise) |
| Diagrams + caveman doc | ✅ `f6086f8` |
| A-1, A-2 — architectural bets | ❌ **no action** (recorded as decisions) |

**762 passed, 16 skipped, ruff clean.**
