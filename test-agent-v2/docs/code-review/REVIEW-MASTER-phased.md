# Code Review & Audit — `test-agent-v2` (whole tree)

**Target:** `test-agent-v2/` — `src/common` (11.1k LOC), `src/gateway`, `src/knowledge_gathering`, `src/test_plan_definition`, `src/test_evaluation`, `src/admin_agent`, `src/testing_agent`, `tools/`, `main.py`, `worker.py`.
**Branch:** `feature/test-agent/v2-adk` · **Date:** 2026-09-19
**Method:** unified two-lens pass — `/code-review max` (correctness · security · efficiency) **and** the **ponytail-review** skill (over-engineering / what to delete). The three previously-reviewed agent packages (KGA / TPD / TEV) were confirmed against current code and folded in as a *remediated baseline*; the 11k-line shared `common/` engine, the gateway, the entrypoints and `tools/` were reviewed fresh by seven parallel reviewers, each finding grep-verified against its actual callers and the deployment Terraform.

---

## How to read this

Findings are grouped into **remediation phases, ordered by priority**. Do a phase before the next.

| Phase | Theme | What's in it | Count |
|---|---|---|---|
| **Phase 0** | Security & data-safety | fail-closed auth, SSRF, destructive-op safety, stored XSS | 1 P0 · 4 P1 · (P3 hardening batched) |
| **Phase 1** | Correctness bugs on live paths | prod recall/read bugs, HITL crash, opaque failures | 3 P1 · 1 P2 |
| **Phase 2** | Robustness & efficiency | retries, validation, OOM guards, self-learning correctness | 12 P2 |
| **Phase 3** | Over-engineering & minor nits | dead code, one-impl abstractions, cosmetic correctness | ~28 P3 |

**Severity key:** **P0** critical (silent security bypass / data loss in a prod path) · **P1** high (real bug or risk on a live path) · **P2** medium (robustness/efficiency/quality) · **P3** low (nit / dead code / speculative flexibility).

Every finding carries its stable per-area ID (`INT-…`, `ADK-…`, `TPL-…`, `MEM-…`, `GW-…`, `ADM-…`, `CLD-…`); the full per-area tables are in the **Appendix** for traceability.

---

## Scorecard

| Lens | Result (newly-reviewed code) |
|---|---|
| **Correctness / Security** | **1 P0 · 7 P1 · 13 P2 · ~22 P3** |
| **Over-engineering (ponytail)** | ~22 cuts identified · **net ≈ −180 to −220 LOC** of dead / speculative code |
| **Overall** | The engine is well-factored and the live *default* paths are sound (LLM-free where promised, blocking I/O offloaded via `asyncio.to_thread` on the hot paths). The risk concentrates in **(a) the auth posture** — a fail-open bearer guarding a *public, destructive* admin surface — and **(b) the hybrid/postgres recall path**, which has two silent correctness bugs (`get_note` misses, DDL-per-request degrades recall). Fix Phase 0 + Phase 1 before this is trusted as a production quality gate. |

**The five that should block:** fail-open bearer on the public destructive surface (**SEC-1**), SSRF via Atlassian attachment fetch (**CLD-01**), `wipe_all`'s `TRUNCATE … CASCADE` re-opening the silent-wipe hole (**ADM-02**), and the two silent hybrid/postgres recall bugs (**MEM-01**, **MEM-02**).

---

## ✅ Resolution (2026-09-19)

All of Phase 0, 1, 2 and 3 were implemented in one pass (via disjoint parallel implementers, each verified with targeted tests). After the changes: **full suite 628 passed, 14 skipped, 0 failed** (was 612 → +16 regression tests); `ruff check src/` **clean**. Not yet committed. The four cross-cutting root causes were fixed once at the shared seam, not per-caller.

| Phase | Findings | Status |
|---|---|---|
| **0 — Security** | SEC-1 fail-open→**fail-closed** bearer (shared `bearer_ok`/`is_open_path`, constant-time, `ALLOW_INSECURE` opt-in, log-once) · CLD-01/02/03 SSRF egress guard (**new `common/net.py`**) + streamed byte caps · ADM-02 dropped `CASCADE` · ADM-03 tooltip XSS escaped · ADK-06/GW-09 `/readyz` leak + `is_open_path` prefix · ADM-04 no token echo | **Done** |
| **1 — Live-path correctness** | MEM-01 `get_note` via O(1) graph index · MEM-02 `build_store` memoized + `_ensure` lock · INT-01 guarded `json.loads` · GW-04 `ask()` raises on `failed` state | **Done** |
| **2 — Robustness** | ADK-02 Vertex retry/backoff+timeout · ADK-03 `Question` parse hardened · ADK-01 no-op `LessonRecallPlugin` **deleted** · INT-02 recall newest-first · INT-03 `to_thread`+fan-out cut · MEM-03 no false-positive recent+cosine floor · MEM-04 CAS lost-update · TPL-01 Gherkin oracle · TPL-03 `order` coercion · GW-03 `ab_latency.py` fixed | **Done** |
| **3 — Over-engineering / nits** | Deleted `LocalObjectStore`, embedder factory, `PgVectorStore` alias, `agenerate` seam, `Config.turbo`, `RedisCache **kw`, `version=` param, `@runtime_checkable`×2, `RoundQuestions` ABC (→dict), no-op latency fns, `_name_of`, `_COMMANDS` registry · deduped TPL-04 distiller · ADM-05 backup dead branch + None-guard · ADM-06 publish race (`ON CONFLICT`+retry) · INT-04/05/07 nits · MEM-06/10 nits · GW-06 `send_raw` loop · GW-07 dead tf var · CLD-06/09/10/12 · dup-import hoist | **Done** (≈ −200 LOC) |

**Deliberately NOT changed (flagged, per plan):** SEC-2 shared-token / public-admin posture (a **deploy/tfvars decision** — make agents private + gateway-only bearer; needs your call, not a code patch); the TPD assured-loop `max_iters=2` default (accepted operational risk); product-decision keeps (CLD-07 cloud registry, ADM-09 `engine` enum, ADM-10 common→agent back-import, CLD-11 markdown parser); the known deferral INT-06 (hub-penalty → pgvector M4). Also left: 5 pre-existing `PLR0402` lint nits in `tools/build_report.py` + `tests/test_plan_workers.py` (untouched files, outside review scope).

> **Still needs a human decision — SEC-2 (the biggest remaining risk).** Fixing SEC-1 made auth fail *closed*, but the agents are still deployed **public** (`bridge_allow_unauthenticated=true`) with a **single shared** bearer, and `admin_agent` (wipe/forget) is one of them. The durable fix is a deploy change: set `bridge_allow_unauthenticated=false` for the agents and have the gateway reach them with a per-service Google ID token (as the Pub/Sub worker already does), keeping the app bearer only on the gateway.

---

## Remediated baseline (already reviewed & fixed — verified still present in current code)

These three packages were reviewed on 2026-09-11/12 and their findings were remediated in the same passes. Spot-verified against current `feature/test-agent/v2-adk`:

- **`knowledge_gathering`** (`REVIEW-knowledge_gathering.md`) — SSRF `_host_blocked` guard **present** in `gather/crawl/fetch/web.py`; `exclude=` now threaded through `gather/agent.py` → `crawl(exclude=…)`; sync-GCS persist offloaded to `asyncio.to_thread`; client-leak, malformed-JSON, budget-drop, cancellation all fixed. *Deliberately kept:* the `NodeFetcher` ABC/registry + `_build_client` seam (test-locked extension points); `atlassian_search` alphabetical tiebreak (won't-fix, no timestamps to sort by).
- **`test_plan_definition`** (`REVIEW-test_plan_definition.md`) — non-object LLM array, unanchored `_match_option`, assured-resume best-round, router blocking reads, scope/kind matching all fixed. **⚠ Standing accepted risk:** the assured loop is **always-on** with `TPD_ASSURED_MAX_ITERS=2` default → `implement_plan` can make **up to 4 serial Vertex calls** by default (tension with invariant I3). Mitigation is operational — set `TPD_ASSURED_MAX_ITERS=1` for latency-sensitive deploys, or size the Cloud Run request timeout for `2·max_iters` sequential model calls. Re-confirmed default is still `2` in `implement/assured/loop.py`.
- **`test_evaluation`** (`REVIEW-test_evaluation.md`) — the three silent-wrong-score seams (M1 3-token `evaluate plan <ctx>` mis-parse, M2 URL-poor faithfulness haystack, M3 over-broad Jira-key regex) fixed; dead fields cut. *Deliberately kept (product decision):* the parallel `eval/` Plan-B ADK-native layer + history/topic/noise metrics (~420 LOC — test-backed nightly gates).

---

## Cross-cutting root causes (fix once, not per-caller)

Four themes explain most of the high-severity findings. The lazy fix is one shared change, not N patched callers:

1. **No egress guard shared across outbound fetchers.** SSRF was fixed in *one* fetcher (KGA web) but the sibling sinks were missed: `common/atlassian/base.py::download_bytes` (**CLD-01**, attachment/remote-link URLs from the ticket under test) and the codegraph tarball fetch (**CLD-03**, size only). → Extract the KGA `_host_blocked` check into a shared `common/net.safe_get()` (resolve host, reject private/loopback/link-local/reserved on every redirect hop, stream with a byte cap) and route *all three* fetchers through it. Kills CLD-01, CLD-02, CLD-03 and prevents the next sink from regressing.
2. **Auth fails open, in two places.** `common/adk/auth.py:19` and `common/bridge/asgi.py:22` both skip the bearer check when the token is unset/empty (**SEC-1** = GW-01/ADM-01). → One shared fail-**closed** helper: on a public-ingress service, an unset expected token must refuse to start (or 503 every non-health route), never serve. Also switch both to `hmac.compare_digest` (ADK-04/ADM-07).
3. **Expensive clients rebuilt per request.** `PgMemoryStore` re-runs the full `SCHEMA_SQL` on every `build_store()` (**MEM-02**, → concurrent DDL → silent graph-only recall) and `build_bank()` reconstructs a GCS-backed store inside async callbacks/tools (**ADK-05**). → Memoize both per process (module-level singleton keyed on the shared engine, as `get_engine` already does) and apply schema once at startup, out of the request path.
4. **Exact-id lookups routed through fuzzy search.** `get_note` resolves an exact id via semantic `search` (**MEM-01**) → misses on any corpus > top-k on the live hybrid backend. → Resolve id→type from the graph index directly (`bank.load_index()`, O(1)), never through search.

---

# Phase 0 — Security & data-safety (do first)

### SEC-1 · Fail-open bearer on a public, destructive surface · **P0** · `common/adk/auth.py:18-19`, `common/bridge/asgi.py:22,44`
Both bearer gates are conditional on the token being set: `if token and header != f"Bearer {token}"`. When `A2A_BEARER_TOKEN` / `GATEWAY_BEARER_TOKEN` is empty or unset, the middleware passes **every** request. The agents deploy with **public ingress** and `bridge_allow_unauthenticated=true` (`terraform.tfvars`), and this middleware is the *only* gate. One of those public services is `admin_agent`, whose tools include `wipe_all` / `forget_memory` / `prompt_publish`.
**Scenario:** the `gateway-bearer-token` / `a2a-bearer` secret is ever populated blank, rotated to empty, or the container is run outside Terraform → the entire destructive admin surface + every memory tier serves **unauthenticated on the internet, with no error**. The control fails open instead of closed. (Mitigated in practice today: the standard TF wires a populated secret and an empty secret *version* fails container startup — so this is P0-impact / lower-likelihood, not P0-live. It still must fail closed.)
**Fix:** fail closed — a public-ingress service with an unset/empty expected token refuses to build the app (or 503s all non-health routes). Log an ERROR at startup when a bearer env is expected-but-missing so a blank secret is never silent. See root cause #2.

### SEC-2 · Shared static bearer + public destructive admin = total blast radius · **P1** · `deployments/test-agent-v2/services.tf` (all services share `a2a_bearer`), `variables.tf:164-167`
A single static `A2A_BEARER_TOKEN` authenticates gateway→agent calls for all four agents *and* is the sole gate on each **public** agent, including `admin_agent`. No per-service token, no rotation seam. If the one token leaks (logs, a compromised client, the `.env` these packages `load_dotenv()`), an attacker calls `admin_agent` **directly** (bypassing the gateway) and issues `wipe_all`/`forget_memory`. The TF even recommends the opposite for the bridge (`variables.tf:203`: "prefer false (private), reach it with a Google ID token") — yet tfvars makes everything public.
**Fix:** make the agents **private** (`bridge_allow_unauthenticated=false`) and let the gateway reach them with a per-service Google ID token (Cloud Run IAM) — exactly as the Pub/Sub worker already does (`pubsub.tf:42,108`). Keep the app bearer only on the one truly-public surface (the gateway). (Related dead knob: unused top-level `variable "allow_unauthenticated"` — GW-07.)

### CLD-01 · SSRF via Atlassian attachment / remote-link fetch · **P1** · `common/atlassian/base.py:75-86` (reached from `knowledge_gathering/gather/crawl/fetch/attachment.py:22`)
`download_bytes(url)` GETs an arbitrary `ident` with `follow_redirects=True` and **no private-IP / metadata guard**. The `ident` is the download URL taken from a Jira/Confluence attachment record — content inside the very ticket the agent was told to test. This is the **sibling SSRF sink the KGA `_host_blocked` fix did not cover.**
**Scenario:** a ticket under test carries an attachment whose URL is `http://169.254.169.254/…` or an internal host → Cloud Run egress fetches it and extracts the body into the pack; internal-network probing / SSRF to internal HTTP services works. (Atlassian Basic-auth *is* correctly stripped on cross-origin redirect, and GCP metadata needs a `Metadata-Flavor` header — so creds don't leak and metadata is hard, but the internal surface is exposed.)
**Fix:** route through the shared egress guard (root cause #1) — reject link-local/private/loopback/reserved before connecting and after each redirect hop; ideally allowlist the site's Atlassian/media hosts.

### ADM-02 · `wipe_all`'s `TRUNCATE … CASCADE` re-opens the silent-wipe hole · **P1** · `common/admin/wipe.py:153`
The `_RUNTIME_TABLES` allowlist was added precisely so a wipe never touches `adk_internal_metadata` / `prompt_template` / `prompt_version` (the 2026-09-17 outage). But `TRUNCATE {t} CASCADE` truncates **any** table holding an FK to a truncated table *regardless of the allowlist* — reintroducing the exact "silently wipe a table we meant to preserve" failure the allowlist defends against. The docstring's "CASCADE … FK-safe" is backwards: listing the co-dependent set in one `TRUNCATE a, b, …` is already FK-safe; `CASCADE` only adds the dangerous direction.
**Scenario:** latent today (preserved tables have no FK into the runtime tables — verified against the DDL); becomes an active outage the moment any future ADK/app table adds an FK referencing a runtime table.
**Fix:** drop `CASCADE`; truncate the full co-dependent set in one statement. An unexpected FK-linked table then raises loudly instead of being silently wiped — the fail-loud posture the allowlist wants.

### ADM-03 · Stored-input DOM XSS in the published memory-graph page · **P1** · `common/admin/graph_html.py:138`
The hover tooltip is built with `tip.innerHTML = '<b>'+n.label+'</b>'+n.type+(n.syn?…:'')`. `n.syn` is escaped; `n.label` (the node title, sourced from crawled Jira/codegraph content) and `n.type` are injected **raw**. The server-side legend escapes types via `html.escape`, but the JS tooltip does not.
**Scenario:** a Jira title like `<img src=x onerror=…>` is stored in the memory bank, surfaced as a node label by `publish_memory_graph`, and executes as inline JS when an operator hovers it in the published page — stored-input → operator DOM XSS. (The Artifact CSP sandboxes external requests, limiting exfiltration, but arbitrary inline JS still runs in the page context.) No test covers escaping here.
**Fix:** escape `<` in `n.label`/`n.type` like `n.syn` already is, or build the tooltip with `textContent` / separate elements instead of `innerHTML`.

**Phase-0 hardening (batch these P3s while you're here):** `wipe_all` refusal echoes the confirm token + discloses the prod bucket name (**ADM-04**); non-constant-time bearer compare in both middlewares → `hmac.compare_digest` (**ADK-04/ADM-07**); `/readyz` leaks missing env-var *names* unauthenticated + `_is_open` uses a loose substring test rather than a prefix (**ADK-06/GW-09**); `_log_filter` interpolates GCP resource names into a Logging filter with no `"` escaping (**CLD-05**, trusted source, low risk).

---

# Phase 1 — Correctness bugs on live paths

### MEM-01 · `get_note` returns "not found" for real notes on the hybrid/postgres backend · **P1** · `common/adk/tools.py:18-26` + `memory/retrieve.py:27-38` + `memory/pg/store.py:104-112`
`get_note(note_id)` resolves an *exact id* by routing it through `search_nodes`. The pg backend's `search` matches tsv over **title+synopsis only** (id/source_url are not indexed) and returns just the top-k (default 40). On `MEMORY_BACKEND=hybrid/postgres` (the live klara-nonprod config) with a corpus > 40 nodes (~266 today), fetching a note whose id (e.g. `confluence:12345`) doesn't literally appear in its title/synopsis → the node isn't in the top-k → `get_note` returns *"No note found for id …"* for a note that exists. Works on `gcs` only by accident (`match_index_nodes` does substring-on-id).
**Fix:** resolve id→type from the graph index directly (`graph,_ = bank.load_index(); node = graph.nodes.get(note_id)`, backend-independent, O(1)), then `read_note_md`. See root cause #4.

### MEM-02 · `build_store()` re-runs schema DDL every request → silent recall degradation · **P1** · `memory/pg/__init__.py:10-15`, `pg/store.py:30-40`, `retrieve.py:58-63`
`build_store()` returns a **fresh** `PgMemoryStore(engine)` on every call, resetting `self._ready` so `_ensure()` re-runs the whole `SCHEMA_SQL` (6 `CREATE … IF NOT EXISTS`, incl. `CREATE EXTENSION` + gin index) on **every** `search_nodes` / `recall_lessons` / self-seed. Every request head pays ~6 DDL round-trips; worse, two concurrent requests issue concurrent `CREATE INDEX/EXTENSION IF NOT EXISTS` → Postgres raises `tuple concurrently updated` / catalog duplicate-key → the broad `except` in `retrieve` swallows it and **silently falls back to graph-only recall** (WARN only). Recall quietly degrades in prod under concurrency.
**Fix:** memoize the store per process (module-level singleton keyed on the shared engine) and apply `SCHEMA_SQL` once at startup, out of the request path. See root cause #3.

### INT-01 · Unguarded `json.loads` crashes the whole refine/define turn · **P1** · `common/interrogate/answers.py:16-24`
`parse_raw_answers` does `if text.startswith(("{","[")): return parse_raw_answers(json.loads(text))` with **no** `JSONDecodeError` guard, and the list/dict branches assume every element is a dict with a `question_id`. On the deployed HITL path (`InterrogationAgent._run_async_impl` → `session.submit(incoming_text(ctx))`), raw human/LLM answer text flows straight in. A reply that merely *starts* with `{`/`[` but isn't valid JSON (a human pastes `{Q-bus-1: yes}`, or an LLM returns `{"answers":["yes"]}`) raises and propagates out of the async generator, hard-failing the refine/define turn. The sibling parser `present.extract_ctx` already guards this exact case — the asymmetry proves it was forgotten.
**Fix:** wrap `json.loads` in `try/except (JSONDecodeError, ValueError)` → fall through to the line-partition parser; skip non-dict items (`if isinstance(a, dict) and "question_id" in a`).

### GW-04 · Failed agent tasks are returned as success (and as an empty string) · **P2** · `common/bridge/a2a_client.py:88-96` + `session.py:32-43`; read-only tools in `knowledge_gathering/bridge/mcp_server.py:47-62`, `test_plan_definition/bridge/mcp_server.py:32-77`, `admin_agent/bridge/mcp_server.py:28-42`
`send()` raises only on a JSON-RPC `error` member. A task that comes back with `status.state=="failed"` is returned normally as `A2AResult(state="failed", text=…)`, and the read-only getters return bare `res.text` with no state check — `extract_text()` returns `""` when the failed task has no message parts. **This is the observed "malformed / empty response" symptom:** a failed run is indistinguishable from success, and shows as an empty string when the failure has no text. (The interrogation tools `refine`/`define_plan`/`implement_plan` prefix `[state: …]`; the getters don't.)
**Fix:** in `session.ask` (one place, all callers route through it) treat `res.state == "failed"` as an error → `raise RuntimeError(res.text or "agent task failed with no detail")`, or have every getter prefix `[state: …]`.

---

# Phase 2 — Robustness & efficiency

- **ADK-02 · No Vertex retry/backoff** · P2 · `common/llm/vertex.py:44-67`. No app-level retry and no explicit `max_retries`/`timeout` on `AnthropicVertex`; `complete()` streams by default, and a mid-stream disconnect/`overloaded_error` after the first token is **not** retried by the SDK. A transient 503 on a long define/implement pass fails the whole step. → Bounded retry (2-3 tries, exp backoff on 429/500/503/overloaded) + explicit `AnthropicVertex(max_retries=…, timeout=…)`.
- **ADK-03 · `Question` per-item validation gap** · P2 · `common/llm/questions.py:40-44`. `Question(**{k: it.get(k) …})` with no guard: a dropped `id`/`question` → `TypeError` discards the *entire* round; `"options": null` overrides the `default_factory=list` → `NoneType` crash later in `render_questions`. → Skip items missing required keys; drop `None` values before constructing; log-and-skip a bad item, don't fail the round.
- **ADK-01 · `LessonRecallPlugin` is a no-op** · P2 · `common/adk/plugins.py:43-53` (wired at `services.py:60`). `before_model_callback` never injects anything on either branch, yet reads as a working lesson-recall hook on the LlmAgent path (the only real recall lives in `interrogation.py`). A maintainer enabling `KGA_RECALL_LESSONS=1` gets nothing, silently. → Implement the injection (append recalled lessons to `llm_request` system content) **or** delete the plugin + its wiring.
- **INT-02 · Recall surfaces the *oldest* lessons and hides its own corrections** · P2 · `common/learn/recall.py:15-16`. Sort key `(i.confidence != "high", i.created_at)` — but lessons are never `"high"` (gather=medium, implement=low), so the first key is constant and `created_at` **ascending** dominates → recall always returns the 5 oldest lessons. A later `CORRECTION` superseding a wrong `GOTCHA` sorts last and never enters the top-5. → Sort newest-first; stable-partition any high-confidence to the front.
- **INT-03 · Recall does an O(all-insights) blocking GCS scan on the loop** · P2 · `common/memory/retrieve.py:53-55` + `learn/store.py`. Under `gcs`, `recall_lessons` runs inline (no `to_thread`) and `iter_lessons` fetches *every* INSIGHT node (kind/status aren't on the index node — `graph.py:107`) then discards non-lessons. With `RECALL_LESSONS` on, each turn is O(all insights) blocking round-trips → Cloud Run timeout risk. `search_lessons` has the same full-scan cost. (Default flag off = safe.) → Wrap in `to_thread`; filter on the edge dict's `origin` (already carries `insight.kind`) or persist `kind`/`status` onto the index node.
- **MEM-03 · Fuzzy search returns unrelated recent nodes on a no-match** · P2 · `memory/pg/store.py:110-111`, `vector_memory.py:163-164`. When a non-empty query matches nothing (no tsv hit, Vertex off), `search` returns `_recent(...)` — arbitrary recent nodes; the vector arm has no distance threshold. `search_memory("nonexistent-xyz")` returns unrelated memory the agent treats as relevant (precision hazard the B-phase fights). → Reserve `_recent` for the *empty-query* case only; return `[]` when a real query yields no hits; add a cosine cutoff.
- **MEM-04 · Blind read-modify-write → lost update** · P2 · `memory/bank.py:177-182` (`append_answers`), `:106-113` (`upsert_note`). Both do RMW with a blind `_put` (no `if_generation_match`), bypassing the bank's own CAS helpers (`mutate_json`, `update_index`). Concurrent `append_answers` → a lost answer; concurrent `upsert_note` of one id from two branches → clobbered links. Latent (flows mostly sequential). → Route both through `mutate_json` / a CAS loop (the retry machinery already exists in the class).
- **CLD-02 · Attachment `max_bytes` checked *after* the whole body is buffered** · P2 · `common/atlassian/base.py:80-83`. `data = resp.content` reads everything into RAM, *then* `len(data) > max_bytes` rejects — the cap is cosmetic. A 2 GB attachment (or an attacker-sized body via CLD-01) OOMs the 2Gi container before the guard fires (second path to the known OOM). → Stream via `client.stream(...)`, honor `Content-Length` up-front, abort once cumulative bytes exceed the cap.
- **TPL-03 · `order` never coerced to `int` → crash after the LLM call is spent** · P2 · `common/testplan/llm/schemas.py:175-179`. `order = s.get('order', i)` straight from the model; Claude-on-Vertex drift can emit `order` as a string on some steps and int on others → the later `sorted(key=lambda s: s.order)` (`report/html.py:94`, `memory/render.py:31`) raises `TypeError`, aborting persist/render *after* generation already paid for the LLM call. → `order = int(s.get('order', i) or i)` in a `try/except (TypeError, ValueError): order = i`.
- **TPL-01 · Gherkin oracle silently dropped from the `.feature` download** · P2 · `common/testplan/report/html.py:230-231` (fallback `:417-419`). `_gherkin_one` emits `Then {expected}` only when `not st.keyword`, so a keyword-bearing step's `expected` (the oracle) never reaches the downloadable `.feature`. When the model records the assertion in `expected` on a `When`/`Given` step with no separate `Then`, the "executable Gherkin" deliverable comes out oracle-less. → Drop the `and not st.keyword` guard (worst case: a redundant, still-valid second `Then`).
- **GW-03 · `tools/ab_latency.py` is broken on every run** · P2 · `tools/ab_latency.py:97` vs def `:38`. The loop calls `_set_env(turbo=…, model_fast=…, batch_mode=…)` but `_set_env` has no `batch_mode` param → `TypeError` immediately, not just in batch mode. It also wires a Phase-B "batch" arm that commit `7364bcc` removed. → Delete the `batch_mode`/`bmode` plumbing and the `AB_MODE=="batch"` arm.

---

# Phase 3 — Over-engineering & minor nits (ponytail cuts + cosmetic correctness)

**Deletions — safe now, no behaviour change (net ≈ −180 to −220 LOC):**

| ID | Location | Cut | Replacement |
|---|---|---|---|
| MEM-05 | `store/local.py`, `store/factory.py:17-20`, `store/__init__.py` | `LocalObjectStore` — half-built (`iter_blobs`/`delete` raise `NotImplementedError`), no `STORE_BACKEND=local` selector | delete; `memory` backend covers offline/test |
| MEM-07 | `embed/factory.py`, `embed/embedder.py`, `memory/pg/embed.py:29-46` | `Embedder` Protocol + `select_embedder` (one branch) + 4 pass-through wrappers + `EMBED_BACKEND` | collapse to `VertexEmbedder.from_env()`; keep the `_get_embedder` cache |
| MEM-08 | `pg/store.py:198-201`, `pg/__init__.py` | `PgVectorStore = PgMemoryStore` alias (referenced only by a test that asserts the alias exists) | delete alias + that test assertion |
| ADK-07 | `adk/providers/base.py:32-33`, `vertex_claude.py:75-77`, `llm/vertex.py:63-67`, `llm/__init__.py:8` | `agenerate` async seam — no production caller (docs say "optional") | delete from Protocol + impl + export; re-add with a real async caller |
| ADK-08 | `adk/config.py:14` | `Config.turbo` field — never read; all consumers call `turbo_on()` reading env directly | delete the field, keep `turbo_on()` |
| ADK-09 | `cache/redis_cache.py:16-21` | `**kw` passthrough to `redis.Redis` — no caller passes any | drop `**kw`; keep the `client=` test seam |
| TPL-04 | `testplan/decision.py:10-35` | `_source_refs`/`_statement`/`rejected` — near-verbatim copy of `interrogate/insight.py` (already drifted on the arrow glyph) | import the shared helpers; keep only the `PlanDecision`-vs-`Insight` construction |
| ADM-05 | `admin/backup.py:16-20` | `_copy_blob`'s `hasattr(store,"copy_blob")` branch — no adapter implements it | delete the dead branch; **add the missing `None` guard** so a concurrent delete doesn't abort the whole snapshot |
| ADM-08 | `prompts/port.py:73,84` | `PromptStore.get(version=…)` param (never passed, ignored by both impls) + unused `@runtime_checkable` | drop both; re-add versioned read when something renders a non-current version |
| GW-06 | `gateway/mcp_server.py:69-84` | `send_raw_kga`/`_tpd`/`_tev` — three identical bodies (`send_raw_admin` already forgotten) | register in a loop over the sessions, or one `send_raw(agent, …)` |
| GW-07 | `deployments/…/variables.tf:164-167` | unused top-level `variable "allow_unauthenticated"` (default false) — never wired; misleads auth audits | delete, or wire the agents to it |
| GW-08 | `admin_agent/agent.py:22-35` | `_COMMANDS` dict + `@command` decorator + import-time global for ~15 handlers in one class | a literal `{"list-runs": self._list_runs, …}` in `_dispatch` |
| INT-08 | `interrogate/round/base.py` + 10 round modules | `RoundQuestions` ABC + `__init_subclass__` singleton registry — a function wearing a class, ×10 | module-level `build_*` fns + one plain `REGISTRY = {…}` dict; delete `base.py` |
| CLD-06 | `cloud/provider.py:10,47` | `@runtime_checkable` on `CloudProvider` — no `isinstance` anywhere (all duck-typed) | delete decorator + import |
| CLD-08 | `benchmark/store.py:26-42` (+ `bridge/session.py:42`, `test_evaluation/benchmark.py:54`) | `add_latency`/`read_latency` — documented no-op under the default `NullCache` | delete both + the two call sites until latency is consumed |
| CLD-09 | `cloud/gcp.py:263-264` | `_name_of` — trivial wrapper, single caller | inline |
| CLD-10 | `report/knowledge.py:93,165` | `from collections import defaultdict` imported twice in function bodies | hoist one to module top |
| CLD-12 | `atlassian/jira.py:12-19`, `confluence.py:15` | double-cap (`maxResults=` **and** `[:max_results]`) | drop the redundant slice |

**Needs a one-line product decision (dead flexibility — flag, don't auto-cut):**
- **CLD-07** `cloud/factory.py:14-23` — `_REGISTRY` + `KGA_CLOUD_PROVIDERS` multi-provider parse resolves to exactly one adapter (`gcp`). Collapse to `{"gcp": GcpCloudProvider()}` unless the Azure/AWS roadmap is committed.
- **ADM-09** `prompts/port.py:22` — `engine` is a persisted one-value enum (`NONE`) with a validate branch that can only pass. Fine to leave (it's a DB column); drop if simplifying.
- **ADM-10** `admin/prompts.py:29-32` — `_registries()` does a `common → agent` back-import, contradicting `memory_view.py`'s explicit "common must not import agent packages" rule. Works in the monorepo image; would `ImportError` if admin were split out. Pick one rule and make the package consistent.
- **CLD-11** `report/util.py:119-170` — hand-rolled ~50-line markdown→HTML parser. **Keep** (reports must be self-contained, tiny controlled subset) — but don't grow it into a general engine; pull a build-time dep if it needs more.

**Minor correctness nits (P3):**
- **INT-04** `interrogate/answers.py:45-53` — a blank answer `text` matches an empty regex against option labels → fabricates a chosen option (then written as an Insight). Treat blank as open/carried.
- **INT-05** `interrogate/insight.py:24` — a free-text (option-less) answer lists *every* option as `rejected` → misleading provenance. Only compute `rejected` when `chosen_option` is non-empty.
- **INT-06** `learn/recall.py:14-16` — recall applies the B5 structural gate but no B4 hub/IDF penalty → a lesson cited by a high-degree hub is recalled for every run touching it (known deferral to pgvector M4).
- **INT-07** `extract/attachment.py:57-133` — untrusted attachment decode has no resource bounds (PDF page count, `PIL.Image.open` before the size check → decompression bomb) and image-transcription text rides into the generator prompt unguarded. Set `PIL.Image.MAX_IMAGE_PIXELS`, cap raw bytes before `Image.open`, cap PDF pages.
- **MEM-06** `memory/pg/project.py:108-116` — `_flush_embeds` appends `job_id` outside the `if vec:` guard → a job is dequeued even on an empty vector (latent; today's adapter is all-or-nothing). Only append when `vec` is truthy.
- **MEM-09** `memory/bank.py:119-128` — `INDEX_MD` `_put` is a blind overwrite outside the CAS retry that guards `INDEX_JSON` (cosmetic — the `.md` regenerates next update).
- **MEM-10** `memory/retrieve.py:22-38` — `search_nodes`'s pg arm returns `{id,type,title}` but the graph fallback returns full raw node dicts; benign today (all callers use only those three fields) but an unenforced shape contract. Project the fallback down to match.
- **ADM-06** `prompts/stores.py:198-204` — `publish` does `SELECT MAX(version)+1` then `INSERT` (RMW); two concurrent publishes of one key both compute N+1 → the second hits the PK and errors. Fold into `INSERT … SELECT …` or `ON CONFLICT … DO NOTHING` + retry. Low probability (single-operator).
- **CLD-03** `codegraph/acquire.py:44-52` — tarball fetched with `tar.content` (fully buffered) and `extractall` has no total-size/member cap (zip-slip itself *is* mitigated via `filter="data"`). Stream with a size limit; cap extracted bytes/count.
- **CLD-04** `codegraph/acquire.py:51` — `tf.getnames()` evaluated twice (scans the archive each time). `names = tf.getnames(); top = …`.

---

## Appendix — full per-area finding tables

Per-area totals (as graded by the seven reviewers, before the master's consolidation/elevation):

| Area | Files reviewed | P0 | P1 | P2 | P3 |
|---|---|---|---|---|---|
| `common/memory + store + embed` (MEM) | memory/, store/, embed/ | 0 | 2 | 3 | 5 |
| `common/interrogate + learn + extract` (INT) | interrogate/, learn/, extract/ | 0 | 1 | 2 | 5 |
| `common/adk + llm + models + cache` (ADK) | adk/, llm/, models/, cache/ | 0 | 0 | 3 | 6 |
| `common/testplan` (TPL) | testplan/ (llm, memory, models, report) | 0 | 0 | 1 | 3 |
| `common/admin + bridge + prompts` (ADM) | admin/, bridge/, prompts/ | 0 | 0 | 3 | 7 |
| `common/cloud + codegraph + atlassian + benchmark + report` (CLD) | cloud/, codegraph/, atlassian/, benchmark/, report/ | 0 | 0 | 2 | 10 |
| `gateway + entrypoints + tools` (GW) | gateway/, admin_agent/, testing_agent/, tools/, main.py, worker.py | 0 | 1 | 3 | 5 |

> The master re-grades a few items across areas for blast radius: SEC-1 (fail-open bearer) → **P0**; CLD-01 (SSRF sibling sink), ADM-02 (CASCADE), ADM-03 (XSS), GW-02 (shared token/public admin) → **P1**; TPL-03 (post-LLM crash) → **P2**. Dedups: fail-open bearer = GW-01+ADM-01; constant-time compare = ADK-04+ADM-07; `/readyz` leak = ADK-06+GW-09.

### Verified clean / explicitly cleared (do not re-investigate)
- **`common/testplan/report` escaping** — every dynamic value flows through `_e`/`html.escape`, `_md`/`_md_inline`, `_mlabel`, or `_download` (URL-encoded `data:` URI). No XSS sink in the report path despite rendering LLM/user content throughout. *(Note: the `admin/graph_html.py` tooltip is a **separate** path and is NOT clean — see ADM-03.)*
- **`worker.py` Pub/Sub** — ack/nack correct (bad envelope → 204 drop; job failure → 500 nack → DLQ after 5); `handle_job` idempotent (result blob keyed by ctx/run/batch); blocking `complete()`+GCS write offloaded via `asyncio.to_thread`. Relies on Cloud Run IAM (`allow_unauthenticated=false` + `run.invoker`) — standard.
- **Text-command bridge** — router `partition(" ")`s on the first token, so a user arg can never change the command verb (no command injection).
- **`common/testplan` seams** — `RoundSession` has two real subclasses exercising every hook; `adk.py` bounds each generator with a timeout and logs every degrade-to-heuristic path; the `JudgeVerdict` emptiness check doesn't misclassify negatives.
- **Ports with two real impls** — `ObjectStore` (gcs+memory), `VectorStore` (pg+in-memory): the in-memory impls are load-bearing test fixtures, **not** over-engineering.
- **Already fixed in v2** (verified, not re-raised) — `atlassian_search` `ORDER BY updated DESC`; gather closes the client it builds; codegraph `filter="data"`; `build_and_store`/`read_logs`/`discover` wrapped in `to_thread`.

---

*Generated by a 7-way parallel dual-lens review (`/code-review max` + ponytail). Per-package detail for the three agent packages lives in the sibling `REVIEW-knowledge_gathering.md`, `REVIEW-test_plan_definition.md`, `REVIEW-test_evaluation.md`.*
