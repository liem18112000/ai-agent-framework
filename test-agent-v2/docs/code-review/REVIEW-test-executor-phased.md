# Code Review — `test-agent-v2/src/test_executor` (the Test-Executor agent)

**Date:** 2026-09-24 · **Baseline:** green (`698 passed, 15 skipped`) · **Scope:** the whole `test_executor` package (1022 LOC, 8 files) + gateway/compose exec wiring + the new TPD generation passes — all added since the 2026-09-23 audit (`6c357a9`) and never reviewed (it was WIP then).
**Method:** dual-lens (`/code-review max` correctness/security + ponytail), 3 focused reviewers, grep-verified against callers, the design doc (`docs/RESEARCH-test-executor-agent.md`), and the shared `common/*` infra.

This agent **executes** test scenarios against real systems — real HTTP (httpx), a real browser (Playwright), and NL→request/browser-plan LLM translation. Scenarios derive from Jira tickets ⇒ **attacker-influenceable**. The design doc names the **per-run egress allow-list** as "the security delta of the whole agent — the primary review surface." That is exactly where the P0 is.

---

## Scorecard

| Lens | Result |
|---|---|
| Correctness / Security | **1 P0 · 6 P2 · 4 P3** |
| Over-engineering (ponytail) | ~2 LOC clean cut; the rest of the flagged scaffolding (`creds_ref`/`health`/`trace_uri` cols, JEV triage cascade) is **design-intended** for documented roadmap features — kept |
| Overall | The engine split is lean and honest (`ran=False` = unbound, never a faked pass); DB I/O is async, SQL parameterized, browser lifecycle closed in `finally`, requests sequential (no concurrency blowout), no auth-header handling yet (no secret leak today), LLM degrades to None rather than raising. Risk concentrates in **(a)** the browser `goto` egress hole (the doc's own primary surface, unimplemented) and **(b)** a small correctness cluster: no run-ledger CAS (double-execute), no per-scenario error guard (wedged run), and a gateway import guard that fails open to a full outage. |

**Egress-guard nuance (load-bearing):** the fix is **NOT** `common/net.host_blocked` — the executor *legitimately* targets internal / `localhost` test environments, which `host_blocked` (blocks private/loopback) would wrongly refuse. The design's model is an **allow-list to the run's `base_url` host**: navigation/requests must stay on the same host as `base_url`, which lets internal test targets through while blocking `169.254.169.254` / `file://` / foreign-host pivots.

---

## Phase plan

| Phase | Theme | Findings |
|---|---|---|
| **0** | Egress & data-safety | EXEC-01 (P0), EXEC-04, EXEC-03, EXEC-06 |
| **1** | Live-path correctness | EXEC-S01, EXEC-05, EXEC-S02, **TPDG-01** (implement dedup off-loop), EXEC-02 |
| **2** | Robustness / nits | EXEC-S03, EXEC-S04, **TPDG-02** (dedup over-merge), EXEC-09, EXEC-P03 |
| **3** | Ponytail (clean cut only) | EXEC-08 (dead `@runtime_checkable` ×2), **TPDG-04** (dead `generate_scenarios` wrapper). Scaffolding (EXEC-07 JEV, EXEC-P01/P02 cols) **kept** — design-intended. |

> **Also reviewed — the new TPD generation passes** (`generate/scenarios.py` `dedup_by_behaviour`, `generate/llm.py` `_crosscutting_scenarios`), both confirmed live on the default `implement` path:
> - **TPDG-01 · P2** `scenarios.py:95` — `dedup_by_behaviour` runs a **blocking Vertex embed + O(n²) Python cosine on the async event loop** (via `claude_scenarios`→`refine_scenarios`, no `to_thread`), breaking the embedder's own off-loop contract; live in prod (`is_configured` only needs `VERTEX_PROJECT`). Event-loop-stall / `ERROR_TIMEOUT` class. **Fix:** `await asyncio.to_thread(refine_scenarios, …)` (or switch to the async `aembed_batch` wrapper).
> - **TPDG-02 · P2 (conf 55)** `scenarios.py:85` — cosine-≥0.86 same-kind *title* dedup can drop legitimately-distinct sub-cases (two BOUNDARY/ERROR variants), silently cutting coverage. **Fix:** add a cheap token-overlap (Jaccard) floor as a second gate, or raise the threshold + document.
> - **TPDG-03 · P3** `_crosscutting_scenarios` is an extra serial Vertex call per assured round — verified *justified* (orthogonal-kind coverage, bounded, degrades), not redundant; gate to round 0 only if latency bites. No bug.
> - **TPDG-04 · P3** `generate_scenarios` wrapper has 0 prod callers + a stale docstring — cut (−10 LOC) or leave (harmless).

Severity: **P0** security bypass / real-system damage on a reachable path · **P1** real bug live path · **P2** robustness/perf/quality · **P3** nit/dead/speculative.

---

## Phase 0 — Egress & data-safety

### EXEC-01 · Browser `goto` navigates to attacker-controlled URLs — SSRF + `file://` read · **P0** · `runners.py:140` (`act` goto), `130-131` (`goto`)
`PlaywrightDriver.act("goto", value=…)` → `page.goto(value or selector)` with the **raw** step value; step values come from `scenario["browser"].steps[*].value` (verbatim scenario content) or the LLM `BrowserStep.value` (free string). The initial `goto` (`runners.py:184`) is `base_url + url_path` (host-bound, safe), but **step gotos are unbounded**. A `ui`/`e2e` scenario with `browser.steps=[{action:"goto", value:"http://169.254.169.254/…"}]` (or `file:///etc/passwd`, or any internal host) drives the `--no-sandbox` chromium there.
**Fix (root cause, covers EXEC-04):** a shared `_same_site(url, base_url)` allow-list check; refuse a `goto` whose host ≠ `base_url` host (and non-http/https). Enforce in `BrowserEngine` for step gotos + assert the built API/browser URLs. (Gated behind `EXEC_RUNNER=auto` + Playwright present today, hence P0-impact / lower-likelihood — but it is the doc's named primary surface and must be closed.)

### EXEC-04 · API/LLM engine outbound requests aren't allow-list-checked (defense-in-depth) · **P2** · `runners.py:76`
`url = base_url.rstrip("/") + "/" + path.lstrip("/")` keeps host = `base_url` today (protocol-relative `//evil` is stripped, `follow_redirects` defaults off), so **not exploitable now** — but a future `headers`/`follow_redirects=True`/absolute-path edit silently reopens SSRF. **Fix:** route the final URL through the same `_same_site` assert so the invariant survives future edits.

### EXEC-03 · No response-body size cap → OOM · **P2** · `runners.py:90-98`
`resp.text` / `resp.json()` / `inner_text("body")` read the entire SUT response into memory unbounded; a multi-GB (or hostile) response bloats the 2Gi container (these agents already OOM-tuned). **Fix:** `client.stream` with a byte cap, or check `content-length` before `.text`.

### EXEC-06 · Failure messages embed full `{method} {url}` + raw exception into the ledger & client reply · **P3** · `runner.py:180`, `runners.py:84,88`
No auth headers are sent today, so nothing leaks now — but if `base_url` ever carries basic-auth/a query token (or a headers feature lands), the full URL + raw transport exception persist to `signals.failures` and return to the client. **Fix:** log the exception; store a host-only / redacted URL.

---

## Phase 1 — Live-path correctness

### EXEC-S01 · Chunked `run_suite` has no CAS — concurrent polls double-execute a chunk · **P2** · `runner.py:154-176`, `store.py:127-147`
The run ledger does `get_run` → mutate → bare `UPDATE … WHERE id=:id` (last-writer-wins), diverging from the sibling agents' `if_generation_match` CAS. Two overlapping `run_suite(ctx)` polls both read `cursor=N`, both execute `scenarios[N:N+chunk]`, both write `cursor=N+chunk` → the **live side effects fire twice** (a duplicated POST/click, not a cosmetic dup). Variant: two fresh starts → two `in_progress` rows → one orphaned forever. **Fix:** add a `version` column; `UPDATE … WHERE id=:id AND version=:expected` (bump on write), bail on 0 rows — or `SELECT … FOR UPDATE` the run row inside the chunk txn.

### EXEC-05 · No per-scenario error guard → a raise wedges the run permanently · **P2** · `runner.py:164-188`
`save_progress` fires only after the whole chunk; the per-scenario loop has no `try`. Any uncaught raise (provider construction, a future path) loses the chunk's counters AND leaves the run `in_progress` with `cursor` un-advanced → the next poll re-runs the same scenario → permanent wedge (client polls forever). Engines swallow their own errors today (so P2, not P1), but the loop shouldn't depend on that. **Fix:** wrap the per-scenario engine call; on error record a failed outcome, advance `cursor`, checkpoint incrementally.

### EXEC-S02 · Gateway WIP import guard catches only `ModuleNotFoundError` → a broken exec module downs the whole gateway · **P2** · `gateway/mcp_server.py:17-20`
The guard's intent is "serve the other agents when test_executor is absent," but it only catches **absence**. A present-but-broken module (a missing name → `ImportError`, or a top-level `SyntaxError`/`NameError`) propagates → **all five agents fail to register**. That's exactly the WIP failure mode the guard exists to survive. **Fix:** `except Exception as exc: … log.warning(...)`.

### EXEC-02 · `heal` executes the LLM-proposed plan before the human gate · **P2** · `runners.py:288`, `runner.py:219`
The "human Yes/No" gates *persisting/applying* the heal patch, but `heal()` re-runs the LLM-proposed corrected plan against the live system to "verify" **first**. For a state-changing corrected request (POST/DELETE) or a healed browser `click`, that mutates the SUT pre-approval. Largely **by-design** for a test-env executor (`run_suite` already executes mutations there) and substantially **de-risked by the EXEC-01 allow-list** (heal can no longer pivot off-host). **Fix (minimal):** none beyond EXEC-01 + a docstring that's honest that verify executes; optionally restrict heal-verify to idempotent methods. *(Decision item — see resolution.)*

---

## Phase 2 — Robustness / nits

- **EXEC-S03 · P3** `agent.py:58-68` — `triage_run` re-runs the JEV/heuristic verdicts already persisted at `finish_run`. Fix: `run.get("triage") or await to_thread(runner.triage, failures)`.
- **EXEC-S04 · P3** `bridge/mcp_server.py:31,47` — command-string args re-split with `partition(" ")`; a space inside `context_id` mis-routes to the `env`/`step` slot. Latent (ids are hex). Fix: reject/length-limit whitespace in `context_id` at the tool boundary.
- **EXEC-09 · P3 (perf)** `runner.py:114-121` — sequential `EXEC_CHUNK(5) × 30s` httpx + LLM + Playwright can approach the 300s Cloud-Run request budget as chunk grows. Not a bug; tune `EXEC_CHUNK`/timeouts. Add a `ponytail:` ceiling note.
- **EXEC-P03 · P3** `store.py` — `exec_run`/`exec_environment` are an unbounded ledger and the `stub` path writes a row per `run` call. Note a retention/prune story when row count matters.

---

## Phase 3 — Ponytail

**Clean cut:**
- **EXEC-08 · P3** `runners.py:54,102` — `@runtime_checkable` on `RunnerEngine` + `BrowserDriver` is never used in an `isinstance` check (grep-confirmed). Drop both decorators (−2 LOC). Keep the Protocols (3 and 2 real impls respectively — justified).

**Kept — design-intended scaffolding (NOT slop):**
- **EXEC-07** JEV decision cascade in `triage` (default OFF, ~35 LOC) — a new instance of the JEV experiment you chose to keep last session; consistent with that decision.
- **EXEC-P01** `exec_environment.kind/revision/creds_ref/health` columns — scaffolding for the documented multi-environment execution (§4) and the **secure-creds-by-reference** model (§3.3); deleting would remove the planned security mechanism.
- **EXEC-P02** `trace_uri` column — scaffolding for the Playwright-trace sink (§3.3).

*(If you'd rather cut the unpopulated scaffolding for "least code," say so — it's inert and re-addable from the design doc.)*

---

## ✅ Resolution (2026-09-24)

Implemented phase by phase; suite **698 → 709 passed, 15 skipped, 0 failed** (+2 new SSRF-guard tests), `ruff check src/` clean. Not committed.

| Phase | Findings | Status |
|---|---|---|
| **0 — Egress/data-safety** | EXEC-01 **P0** `_same_site` allow-list at the browser `goto` sink (steps resolved against base_url + host-pinned; the raw `act("goto")` sink removed) + the ApiEngine tripwire (EXEC-04) · EXEC-03 streamed response body cap (`_MAX_RESPONSE_BYTES`) · EXEC-06 host-free failure messages + exception-type only (log full server-side) | **Done** |
| **1 — Correctness** | EXEC-S01 one-active-run-per-context (conditional insert, both stores) · EXEC-05 per-scenario try → advance cursor, never wedge · EXEC-S02 gateway `except Exception` · TPDG-01 `refine_scenarios` (blocking embed+cosine) offloaded via `to_thread` ×2 · EXEC-02 honest heal docstring (verify executes, bounded by the allow-list; only the patch is human-gated) | **Done** |
| **2/3 — Nits + ponytail** | EXEC-S03 reuse persisted triage verdicts · EXEC-08 dropped dead `@runtime_checkable` ×2 · TPDG-04 corrected the stale `generate_scenarios` docstring | **Done** |

**Deliberately not code-changed:**
- **TPDG-02** — a token-overlap 2nd gate was implemented then **reverted**: the semantic-dedup pass exists precisely to merge low-token-overlap-but-semantically-identical titles (the golden-zip test: 3 differently-worded copies share almost no tokens), so an overlap floor defeats its purpose and broke that test. Left a ceiling comment; the real knob is the already-env-tunable `TPD_DEDUP_THRESHOLD` (raise toward ~0.92 if sub-case merges appear).
- **EXEC-S04** (whitespace in `context_id` mis-split) and **EXEC-09 / EXEC-P03** (chunk-latency ceiling · unbounded ledger) — P3-latent; left as documented notes rather than editing `runner.py`/`agent.py` while that file is under concurrent `test_executor` development (multi-env/creds feature actively landing).
- The design-intended scaffolding (JEV triage cascade, `creds_ref`/`health`/`trace_uri` columns) — **kept**; the concurrent work is actively wiring the per-env creds path (an `auth` param now on `RunnerEngine`), confirming that call.

---

## Verified NOT bugs (checked)
DB I/O is on the async engine (no event-loop block); the sync JEV `triage` + memory-bank `load_scenarios` are correctly `to_thread`-wrapped; all SQL is parameterized `text()` with static identifiers (no injection); `heal`/`triage` never persist/apply a patch (non-destructive by design); sequential-poll resume is correct + tested; browser lifecycle closed in `finally`; ApiEngine URL host-bound today; no auth-header handling ⇒ no secret leakage today; requests strictly sequential (no concurrency blowout).
