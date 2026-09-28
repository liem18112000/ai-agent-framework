# Code Review & Audit — `test-agent-v2` · branch `feature/test-agent/final-v2-release`

**Date:** 2026-09-23 · **Baseline:** green (`661 passed, 15 skipped`, 91.7s) · **Lint:** `ruff` clean at start.
**Method:** two-lens MAX pass — `/code-review max` (correctness · security · performance) **and** the **ponytail** lens (over-engineering / what to delete). Five parallel reviewers, every finding grep-verified against real callers, deployment `.env.compose`, and `docker-compose.yaml`.

**Scope:** the ~1,500 LOC of code added since the last whole-tree audit (`59b7417`, branch `v2-adk`, already merged & remediated) plus a fresh whole-tree over-engineering sweep. New since baseline: the docker-compose **Claude-subscription local stack** (claude-proxy shim, LiteLLM provider, Redis/MinIO/Ollama/Postgres, redis-queue worker), the **JEV decision provider**, **parallel gather fan-out + source-gate**, **GitHub source-file fetch**, **diagrams-as-code + deliverables**, the **prompt store**, and the **CAS artifact registry**.

---

## What this compose stack actually activates (the deletion discriminator)

`.env.compose` selects the *second* real implementation of every port, so these seams **earn their keep — do not cut:** `STORE_BACKEND=s3` (MinIO), `CACHE_BACKEND=redis`, `VECTOR_BACKEND=pgvector`, `EMBED_BACKEND=ollama`, `TESTAGENT_MODEL_BACKEND=litellm` (→ claude-proxy), `TPD_GEN_MODE=workers` (→ `redis_worker.py` → `queue.py`), and `TPD_DECISION_BACKEND=jev` with **`TYPESAFE_API_KEY` populated locally** (blank only in the tracked example).

Two consequences that overturn first-pass findings:
- **`workers.py` is NOT dead** (compose runs a `worker` service on `redis_worker.py` → `handle_job`). *Rejected: "delete workers.py".*
- **JEV is NOT dead for this user** — the key is set, so `_decision_gate` / the semantic judge fire locally. That promotes the JEV blocking-on-async and confidence-default bugs from "latent" to **live**, and makes deleting the JEV subsystem a product decision (below), not a cleanup.

Genuinely-dead selectable backends (no config, no deployment, only a self-test each): `InMemoryVectorStore`, `LocalFsObjectStore`, `InMemoryCache`. `InMemoryObjectStore` is **kept** — it's the shared test double with many consumers.

---

## Scorecard

| Lens | Result |
|---|---|
| Correctness / Security / Performance | **1 P1 · 6 P2 · 8 P3** |
| Over-engineering (ponytail) | **~570 LOC** clean dead-code/flex cuts · **~1,200 LOC** more behind two product decisions |
| Overall | New code is well-factored and the default paths degrade safely (fan-out bounded + `return_exceptions`, CAS registry & prompt-store races verified safe, batch gen degrades per-batch, most GCS I/O offloaded). Risk concentrates in **(a)** the local **claude-proxy** exposed unauthenticated on `0.0.0.0` and **(b)** the **implement path's serial-LLM-call count**, which quietly regressed the "≈1 call" invariant to ~8–18 serial Vertex calls per MCP call. |

**The ones that should block a release:** PROXY-01 (unauth subscription proxy on all interfaces), KGA-01 (uncapped GitHub fetch → OOM from ticket content), TPD-01/TPD-02 (implement serial-call blow-up → Cloud-Run timeout on rich packs).

---

## Phase plan

| Phase | Theme | Findings | Auto-fix? |
|---|---|---|---|
| **0** | Security & data-safety | PROXY-01, PROXY-02, STORE-01, INFRA-05 | Yes |
| **1** | Live-path correctness & performance | KGA-01, KGA-02, TPD-01, TPD-02, TPD-03, JEV-01 | Yes |
| **2** | Robustness / hardening | JEV-03, JEV-06, KGA-03, KGA-06, PROXY-03, TPD-07, TPD-09, WORKER-02(doc) | Yes |
| **3** | Ponytail — clean deletions | JEV-04, TPD-04, TPD-08, KGA-04, PONY-03, PONY-04, PONY-05, laya.pyc | Yes |
| **4** | Ponytail — product-decision deletions | PONY-01 (cloud tier ~865), PONY-02 (JEV ~340+827) | **Needs your call** |

Severity: **P0** silent security-bypass / data-loss on a reachable path · **P1** real bug on a live path · **P2** robustness/perf/quality · **P3** nit / dead code / speculative flexibility. (This is dev-facing infra; proxy exposure is rated at true security severity but noted as LAN-scope.)

---

## Phase 0 — Security & data-safety

### PROXY-01 · Unauthenticated Claude-subscription proxy published on `0.0.0.0` · **P1** · `docker-compose.yaml:103`
`claude-proxy` (`server.py`) accepts any `POST /v1/chat/completions` and shells `claude -p` with the mounted subscription creds — zero auth. `ports: ["8088:8088"]` binds it on all host interfaces, so any LAN peer can burn the paid subscription / run prompts as the user. The port is **unused by the stack** (agents reach it over the compose network `http://claude-proxy:8088`; `run-local.sh` uses `docker compose exec`). **Fix:** delete the `ports:` line (or bind `127.0.0.1:8088:8088`). *−1 line.*

### PROXY-02 · Proxy is unbounded — subprocess/request, no body cap, runs as root · **P2** · `src/claude_proxy/server.py`
`ThreadingHTTPServer` spawns a `claude` CLI per request; `self.rfile.read(Content-Length)` trusts the header (unbounded alloc); Dockerfile sets no `USER`. **Fix:** reject `Content-Length` over a few MB; optional `threading.Semaphore` around `run_claude`.

### STORE-01 · boto3 floor predates conditional-PutObject CAS · **P2** · `pyproject.toml`
Default local `STORE_BACKEND=s3`; its create/update CAS uses `IfMatch`/`IfNoneMatch` on `put_object`, added ~botocore 1.35.60. Pin is `boto3>=1.34` → an early resolve raises `ParamValidationError` and silently breaks every create-CAS write. **Fix:** `boto3>=1.35.60`.

### INFRA-05 · Backing services on `0.0.0.0` with default/no creds · **P3** · `docker-compose.yaml`
MinIO (`minioadmin:minioadmin`), Postgres (`taagent:taagent`), Redis (no auth), Ollama all bind all interfaces; the MinIO store can hold crawled Jira/Bitbucket content. **Fix:** prefix host bindings with `127.0.0.1:` for anything not meant to be shared.

---

## Phase 1 — Live-path correctness & performance

### KGA-01 · GitHub source fetch has no byte cap; buffers whole file into RAM · **P2 (release-blocking)** · `common/atlassian/github.py:24`, `base.py`
`get_github_src` → `_request` does a buffering `get(...).text`; docstring admits "up to 100MB". `github:` nodes are on the **default** gather path; owner/repo/path derive from **untrusted ticket content** and crawl fetches at `concurrency=8` → up to ~GB-scale transient → OOM-kill on a 2Gi instance (gather already ~517Mi). Every sibling fetcher streams+caps (web 2MB, `download_bytes` 25MB). **Fix:** give raw GitHub content a streamed+capped path (mirror `web.py`), or a `Content-Length` guard before read.

### KGA-02 · Sync GCS `load_index()` on the event loop in the new pre-crawl fan-out · **P2** · `explore/expand.py:110`, `seeds/ground_leads.py:52`
`memory_self_seed` (sync, runs on ~every gather) and `ground_leads` call blocking `bank.load_index()` (GCS download) directly on the loop — the exact class the `crawl._persist` `to_thread` offload was written to fix; the new path skipped the discipline. **Fix:** `await asyncio.to_thread(...)` both.

### TPD-01 · `implement_plan` makes ~8–18 serial Vertex calls per MCP call; docstring says 4 · **P1** · `implement/assured/loop.py:181,205,230`
Per MCP call (one chunked round, defaults): `1` scope-classify + `ceil(in_scope_units/3)` scenario batches (serial, `_BATCH_CONCURRENCY=1`) + `3` judge samples (serial) ≈ 8 typical, up to ~18 for a rich unclassified pack. The predictive budget guard bounds **rounds**, not **batches within a round** (`round_durations` is empty on the sole round of a chunked call), so a large pack's `ceil(41/3)=14` serial batches × per-batch timeout can exceed the ~300s MCP idle ceiling → `implement_plan` errors (the documented Cloud-Run-timeout incident class). The docstring's "2·iters=4" is wrong. **Fix:** make the budget guard batch-aware (or cap in-scope units per round); correct the docstring.

### TPD-02 · `TPD_JUDGE_SAMPLES` default 3 → triples judge latency every round · **P2** · `implement/assured/loop.py:40`
Median-of-3 judge sampling runs on the default path (decision provider result aside), adding 2 extra serial Vertex calls/round for a small variance win. **Fix:** default `_DEFAULT_JUDGE_SAMPLES = 1`; let latency-tolerant deploys opt up. *Fastest single lever back toward the ≈1-call invariant.*

### TPD-03 · Blocking GCS I/O on the async loop throughout implement · **P2** · `implement/generate/pipeline.py`, `implement/assured/loop.py`
`implement_plan`/`run_assured_scenarios` are `async` but every `store.read_*/write_*` (per-round `_persist`, plan/scenario/test-data/coverage/diagram writes) is a synchronous GCS call inline; the router already threads its reads. **Fix:** wrap the implement hot-path store I/O in `asyncio.to_thread` (or a threaded store facade).

### JEV-01 · Blocking sync JEV network call on the async implement loop · **P2 (live for this user)** · `implement/assured/loop.py:222`
`_decision_gate` (sync) → `decision.score()` → blocking HTTP, invoked with no `await`/`to_thread` inside `async run_assured_scenarios`. With `TPD_DECISION_BACKEND=jev` + key set (this user's local config), it blocks the loop mid-implement. **Fix:** `verdict = await asyncio.to_thread(_decision_gate, ...)`. (Sibling `score_rank` is already `to_thread`'d — this is an inconsistency, not a design choice.)

---

## Phase 2 — Robustness / hardening

### JEV-03 · `TYPESAFE_DEFAULT_CONFIDENCE=1.0` silently disables the LLM-judge fallback · **P2** · `providers/jev.py:74`
`_conf` guesses among three attribute names; a missing/renamed field returns default `1.0`, and the gate `confidence >= 0.8` then always short-circuits the real judge whenever `score>=threshold` → "confidently accept, skip the judge" on an uncalibrated backend. **Fix:** default to `0.0` (below `TPD_DECISION_CONF_MIN`) so a missing field keeps the judge in the loop; pin the real field name once the SDK is stable.

### JEV-06 · JEV noul judge branch has no error handling · **P3** · `test_evaluation/eval/judge.py:77`
Unlike the loop and source-gate call sites, the judge closure calls `decision.noul(...)` bare — a JEV outage crashes semantic scoring instead of falling through to the LLM judge below. **Fix:** `try/except → fall through`.

### KGA-03 · GitHub fetch is the only outbound fetcher not routed through `common.net.host_blocked` · **P3** · `common/atlassian/base.py:63`
Not exploitable today (host is trusted env config, `follow_redirects=False`), but every sibling is guarded; the day someone flips redirects or makes `github_base` config-driven this becomes an SSRF + Enterprise-token-exfil sink. **Fix:** one-line `host_blocked` at the top of `_request` (defense-in-depth).

### KGA-06 · GitHub raw fetch returns a 3xx body as file content · **P3** · `common/atlassian/base.py:74`
`follow_redirects=False` + `raise_for_status()` doesn't raise on 3xx → a 302 on a `github:` fetch hands back the redirect page as the "file". Low probability, silent-wrong. **Fix:** treat 3xx on the raw path as an error → gap.

### PROXY-03 · Empty completion returns the raw JSON blob · **P3** · `src/claude_proxy/server.py:34`
`j.get("result") or j.get("response") or out` falls through to the whole JSON on `{"result": ""}`. **Fix:** `return j["result"] if "result" in j else j.get("response", out)`.

### TPD-07 · `prompt_publish` has no body-size cap; every version retained forever · **P3** · `common/admin/prompts.py`, prompt store `publish`
`_MAX_BODY` is display-only truncation; publish imposes no length limit and the store is append-only → unbounded growth; a huge body becomes the cached system prompt. Admin-gated → low. **Fix:** reject bodies over a sane cap (e.g. 32KB) in `publish`.

### TPD-09 · `classify_in_scope` re-runs (1 LLM call + `write_plan`) per chunked call, not once per implement · **P3** · `implement/assured/loop.py:180`
Comment claims "one per implement" but it sits at the top of `run_assured_scenarios`, re-entered on every chunk/resume → extra LLM call + GCS write per resume. **Fix:** persist `in_scope_ids` on the first chunk and skip on resume, or correct the comment.

### WORKER-02 · Misleading redelivery docstring on the Redis path · **P3** · `common/queue.py`, `workers.py::handle_job`
Redis path has no `XAUTOCLAIM`; an unacked job is never redelivered (in-code `ponytail:` note names this ceiling) but `handle_job`'s docstring still says "Pub/Sub redelivers". **Fix:** correct the docstring (leave the ceiling as-is for local).

---

## Phase 3 — Ponytail: clean deletions (safe, ~570 LOC)

Each verified: zero non-test callers / no config selects it / author-documented as no-benefit.

| ID | Cut | LOC | Evidence |
|---|---|---|---|
| **JEV-04** | `DecisionProvider.choice` + `JevProvider.choice` + `_call` "choice" entry + `_verdict` branch | ~12 | `grep '\.choice('` → 0 callers |
| **TPD-04** | `implement/assured/agent.py` (`AssuredScenarioAgent`/`build_assured_agent`) + exports + its isolated test; fix 2 stale docstrings | ~69 | never wired into any orchestrator; engine `run_assured_scenarios` is what runs |
| **TPD-08** | `restater=` injection seam (`define/plan.py`, `define/session.py`) | ~16 | no prod caller passes it; flagged in prior REVIEW doc too |
| **KGA-04** | parallel planners (`_planner_parallel`, `_run_planner_isolated`, parallel branch) + `tests/test_planner_parallel.py` | ~97 | author docstring: "~0 speedup, known empty-output hazard"; not tf-wired; serial path already present |
| **PONY-03** | `InMemoryVectorStore` (`vector_memory.py`) + `memory` branch + self-test | ~222 | no config sets `VECTOR_BACKEND=memory`; pgvector already returns `None` with no DB |
| **PONY-04** | `LocalFsObjectStore` (`store/local.py`) + `local` branch + self-test | ~125 | compose uses `s3`, prod `gcs`, tests `memory`; no config selects `local` |
| **PONY-05** | `InMemoryCache` (`cache/memory.py`) + `memory` branch + self-test | ~33 | compose uses `redis`, default `NullCache`; only a self-test |
| — | stale `providers/__pycache__/laya.cpython-312.pyc` (deleted module) | 0 | leftover of commit f9a1ab8 |

> Note on the three dead backends (PONY-03/04/05): each is a *selectable* backend, so deleting it removes a config option nobody uses. Aligned with the "least code" mandate; if you'd rather keep the optionality, say so and I'll leave them (they're inert, so they cost only LOC).

---

## Phase 4 — Ponytail: product-decision items (DECIDED 2026-09-23)

### PONY-01 · Cloud-discovery tier (KGA tiers 5/6/7) · **DECISION: slim the seam, keep the feature**
Feature kept (tiers 5/6/7 stay on the roadmap). Cut only the speculative multi-cloud indirection: collapse the 1-impl `CloudProvider` Protocol + `_REGISTRY` factory into direct `GcpCloudProvider` construction (~−90 LOC). Gate flag `KGA_GCP_ENV_MATRIX` and all call sites unchanged.

### PONY-02 · JEV / `DecisionProvider` subsystem · **DECISION: keep + fix bugs**
JEV is active in the user's local stack (key set) → kept. Fixes fold into the phases above: JEV-01 (Phase 1), JEV-03/JEV-06 (Phase 2), JEV-04 dead `choice()` (Phase 3), plus trim the 1-entry `_DECISION_REGISTRY` to direct `JevProvider` construction (~−25 LOC). The 827 LOC of `tools/` calibration scripts are kept (dev tooling for the in-progress experiment).

---

## ✅ Resolution (2026-09-23)

All phases implemented and verified. Suite **661 → 688 passed, 15 skipped, 0 failed** (net of +3 new regression tests, −1 deleted test file, and concurrent `test_executor` additions); `ruff check src/` **clean**. Not committed.

| Phase | Findings | Status |
|---|---|---|
| **0 — Security** | PROXY-01 all published ports → `127.0.0.1` (proxy no longer LAN-reachable) · PROXY-02 body cap + concurrency semaphore + `no-new-privileges` · PROXY-03 empty-completion fix · STORE-01 `boto3>=1.35.60` · INFRA-05 host-only bindings | **Done** |
| **1 — Live-path correctness & perf** | KGA-01/03/06 one streamed+capped+SSRF-guarded `stream_text` for raw GitHub (shared `_read_capped` with `download_bytes`) · KGA-02 `to_thread` the 3 pre-crawl `load_index` calls · TPD-01 batch-aware cap (`TPD_GEN_MAX_BATCHES`, overflow heuristic-filled) + corrected docstring · TPD-02 `TPD_JUDGE_SAMPLES` default 3→1 · TPD-03 implement path GCS I/O offloaded (`_persist` async + pipeline `to_thread`) · JEV-01 `to_thread` the decision gate | **Done** |
| **2 — Robustness** | JEV-03 confidence default 1.0→0.0 (fail-safe) · JEV-06 JEV judge falls back to LLM on outage · TPD-07 prompt-body cap in shared `validate()` · TPD-09 corrected the per-chunk-classify comment · WORKER-02 corrected redelivery docstring | **Done** |
| **3 — Ponytail (clean cuts)** | JEV-04 dead `choice()` removed (Protocol + impl + fake + test) · KGA-04 parallel planners removed (~−110 incl. test) · stale `laya.pyc` removed | **Done** |
| **3 — Ponytail (kept, your call)** | PONY-03/04/05 dead backends **KEPT** (pluggable-ports architecture; `local.py` was deliberately re-added) · TPD-04 `AssuredScenarioAgent` **KEPT** · TPD-08 `restater=` seam **KEPT** | **Kept** |
| **4 — Product-decision** | PONY-01 collapsed the 1-impl cloud `_REGISTRY` (feature + `CloudProvider` type-contract kept) · JEV 1-entry `_DECISION_REGISTRY` collapsed to direct construction | **Done** |

**Net:** all P0/P1/P2 fixed; new code ~−120 LOC (choice + planners + registries) with the built architecture preserved per your decisions. **Deliberately not changed:** SEC-2-class posture is moot locally (host-only bindings + `ALLOW_INSECURE` dev gate); the deep `CloudProvider`/`DecisionProvider` Protocol removals were scoped down to registry-collapse only (the Protocols are the type-contracts for the kept roadmap features).

---

## Verified NOT bugs (checked, so they aren't re-flagged)

CAS artifact registry (`admin/runs.py`) is race-safe across all four stores; prompt-store `publish` is race-safe (`INSERT…SELECT MAX+1…ON CONFLICT…RETURNING` + retry) and rejects undeclared `$placeholder`s; `diagrams.py` is data-only (emits `.mmd`, strips angle brackets) — no XSS; workers coordinator offloads publish/poll via `to_thread`; batch gen degrades per-batch (`run_json_agent` swallows → heuristic); gather fan-out is bounded (`Semaphore`, tf-wired) and degrades per-producer; `source_gate` is fail-open; proxy uses argv `subprocess.run` (no shell injection); s3 CAS re-heads before conditional PUT (no TOCTOU); ollama embed offloads + degrades to NULL vectors. `ModelProvider` (2 impls), `NodeFetcher` (8), `net.host_blocked`, `KGA_FANOUT_CONCURRENCY`, `KGA_SOURCE_GATE`, `InMemoryObjectStore` (test double), s3/redis/ollama/litellm/pgvector/redis-queue backends — all genuinely used, keep.
