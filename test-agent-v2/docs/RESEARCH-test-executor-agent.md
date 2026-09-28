# Test Executor Agent — design report

**Purpose.** The **fourth main A2A agent** of the Testing Agent — the **Test Executor (EXEC)** — the
**Pillar-2** stage that turns the Gherkin `.feature` the Test-Plan Definition (TPD) agent exports into a
*real, multi-environment test run*, then (roadmap) feeds its execution signals back into the
Test-Evaluation (TEV) scores. **This agent is now BUILT** (`src/test_executor/`) — this doc is the design
spec plus a running **implementation-status** reconciliation (updated 2026-09-24).

> **Implementation status (2026-09-24).** The agent is live: a 4th A2A service on the gateway
> (`AGENT=test_executor`, `EXEC_A2A_URL` / `register_exec`), keyed by `context_id`, with all five tools
> (`run_suite` · `triage_run` · `heal_step` · `get_run_report` · `list_environments`). **Built:** the
> chunked/polled/resumable `run_suite`; three real engines routed by scenario `methodology`
> (`ApiEngine` httpx-conformance · `LlmEngine` NL→request · `BrowserEngine` real Playwright chromium with
> an LLM NL→browser-plan translator); a **home-grown OpenAPI oracle** (`openapi.py`: spec fetch → operation
> match → status + jsonschema response-schema conformance — **not** Schemathesis); **multi-environment**
> execution (`EXEC_ENVIRONMENTS` named targets + per-env `auth.py`: bearer / bearer_fetch / login);
> **file-upload** tests (multipart, bytes as an inline base64 bank fixture via `data_ref`); the run ledger
> (`exec_environment` + `exec_run` on the shared Cloud SQL engine); a per-run egress **allow-list**
> (`_same_site` pins the exact `base_url` origin); and heuristic + JEV-fronted **triage** + LLM **heal**
> (propose-and-verify, human-gated patch). **Deferred (design below, not built):** the heavy surveyed tools
> (Schemathesis / RESTler / Hypothesis / Playwright-BDD·behave / Playwright-MCP / Test-Agents / Healenium /
> mutation engines / Applitools / Pact), **differential** cross-env mode, JEV for heal-accept /
> flakiness×5 / env-selection, and the whole **TEV extension** (§6 — `evaluate_run`, real
> `fault_detection`). The gate discipline, GCS-resume, and JEV-default-OFF invariants hold.

> **Original framing (2026-09-23, superseded above).** This doc was rewritten from the earlier Pillars-2&3
> *survey* into a focused **design spec** answering, in order: **(1) main architecture · (2) detailed flow ·
> (3) implementation details · (4) multi-environment execution + per-env database · (5) JEV judge &
> evaluation · (6) how it extends the TEV stage.** The tooling landscape is a compact reference tail (§8).

> **Companion reports.**
> - Upstream generator (what produces the `.feature`) — [`RESEARCH-tpd-assured-generation.md`](./RESEARCH-tpd-assured-generation.md).
> - The oracle concept the Executor makes real — [`RESEARCH-test-oracle.md`](./RESEARCH-test-oracle.md).
> - JEV typed-decision backend — [`RESEARCH-jev-in-test-agent-v2.md`](./RESEARCH-jev-in-test-agent-v2.md).
> - Scoring the pipeline output (what the Executor upgrades) — [`RESEARCH-tpd-evaluation-adk-testsuite.md`](./RESEARCH-tpd-evaluation-adk-testsuite.md).

> **Diagrams — one per section of this report** (open the `.excalidraw` to edit; PNGs render inline):
> - §1 Main architecture — [`exec-architecture.excalidraw`](./exec-architecture.excalidraw) · [`.png`](./exec-architecture.png)
> - §2 Detailed flow — [`exec-flow.excalidraw`](./exec-flow.excalidraw) · [`.png`](./exec-flow.png)
> - Pipeline seam — where EXEC slots in — [`exec-pipeline-seam.excalidraw`](./exec-pipeline-seam.excalidraw) · [`.png`](./exec-pipeline-seam.png)
> - §4 Multi-environment + per-env DB — [`exec-multienv-db.excalidraw`](./exec-multienv-db.excalidraw) · [`.png`](./exec-multienv-db.png)
> - §5 JEV judge & the cascade — [`exec-jev-cascade.excalidraw`](./exec-jev-cascade.excalidraw) · [`.png`](./exec-jev-cascade.png)
> - §6 How it extends TEV — [`exec-tev-extension.excalidraw`](./exec-tev-extension.excalidraw) · [`.png`](./exec-tev-extension.png)
>
> Cross-agent context: the Assured Test Loop ([`agentic-qa-assured-loop.png`](./agentic-qa-assured-loop.png)) and the roadmap ([`agentic-qa-enhancement-roadmap.png`](./agentic-qa-enhancement-roadmap.png)).

---

## 0. TL;DR — the `.feature` is now executable (the stage exists)

Before EXEC the pipeline was `gather → refine → approve → [evaluate_pack] → define_plan → approve_plan →
implement_plan → get_scenarios → [evaluate_plan]`: `implement_plan` exported a Gherkin `.feature` "for the
downstream Test execution stage" **that did not exist**, so the pipeline generated scenarios (scored by the
TPD assured loop) then **stopped** — nothing ran, and downstream quality numbers were **deterministic
proxies** (`oracle_strength`, `fault_class_coverage`) standing in for signals only a real run can produce.

The Test Executor is that stage, now shipped. It is a **4th A2A agent**, sibling to KGA/TPD/TEV, keyed by
the **same `context_id`**, that: runs the persisted scenarios against a **selected target environment**
(`run_suite`, chunked/polled/resumable); routes each scenario by `methodology` to a real engine and wraps
each API step in an **OpenAPI conformance oracle** (status + response-schema, not `assert 200`) with a
per-run egress **allow-list**; resolves **per-environment credentials** from a secret *reference*;
**triages** each failure (Bug / Heal / Flaky / Env, heuristic + optional JEV); proposes a **heal** patch for
a failing step under a human gate; and records **each tested environment and each run to Postgres**. The
pipeline stays **linear and human-gated on the outside**; the Executor adds a bounded
**run → (triage) → (heal)** inner loop. *Still a proxy today:* the TEV feedback (§6 — real mutation /
coverage-delta) and multi-env **differential** mode are designed but not yet built.

---

## 1. Main architecture

![Test Executor main architecture: a Claude Code client (owning the Yes/No gates) speaks MCP to the single MCP Gateway, which fronts four A2A agents — KGA, TPD, TEV, and the NEW EXEC — each registered identically (EXEC via EXEC_A2A_URL + register_exec). EXEC kicks off and polls a Run Sandbox (Playwright · behave · Schemathesis) off the request path; the sandbox holds test-env creds + controlled egress and is a distinct trust boundary. All agents share the same reused state, keyed by context_id: Cloud SQL (env registry + run rows NEW, plus task store · sessions · pgvector), GCS (run.json · traces · heal patches), and the graphify codegraph.](./exec-architecture.png)

The Executor is **the same shape as the three existing agents** and reuses every seam the pipeline already
has — that is the whole point: no new datastore, no new protocol, no new gateway.

**The five load-bearing decisions:**

1. **A 4th A2A agent, not a mode of TEV.** It holds credentials and drives live systems — a trust boundary
   the read-only KGA/TPD/TEV never crossed. Keep it a separate deployable so its blast radius, IAM, and
   network egress are isolated. It registers on the gateway *identically* to the others
   (`EXEC_A2A_URL` + `register_exec(mcp, exec_session)`), keyed by `context_id`.

2. **The runner lives in a sandbox the agent *kicks off and polls*, never in the request path.** A full
   test run is far heavier than the three serial Vertex calls that once blew the Cloud Run
   liveness/request timeout (memory: *implement serial Vertex calls → Cloud Run timeout*). The A2A tool
   starts a job, returns `[state: in_progress]`, and the client re-polls — exactly the multi-turn contract
   `implement_plan` already uses.

3. **Deterministic-first, agent-only-to-heal.** The winning production pattern (Octomind's "AI doesn't
   belong in test runtime"): **agent discovers a step once → compile it to a deterministic locator → the
   LLM re-engages only when a step fails.** The steady-state run is fast and repeatable; the model is a
   *healer*, not an interpreter, on every step.

4. **Every oracle upgrade rides the OpenAPI surface the services already expose.** `assert 200` becomes
   "conforms to the contract" for free — no new spec authoring (§3.2).

5. **State reuses what exists.** Loop/run state → **GCS** under `context_id` (resume-not-restart, the
   discipline the TPD assured loop already uses). Tested-environment + run metadata → the **shared Cloud
   SQL Postgres** that already backs the task store and ADK sessions (§4). Typed decisions (triage,
   heal-accept, flakiness) → the **JEV `DecisionProvider` port** already added beside `ModelProvider` (§5).

**A2A Agent Card — tools** (all implemented; registered on the gateway exactly as KGA/TPD/TEV tools are):

| Tool | Shape | Role |
|------|-------|------|
| `run_suite(context_id, env=None)` | multi-turn (`in_progress`→`done`) | Run the persisted `.feature` against the selected/chosen environment; kick-off + poll. |
| `heal_step(context_id, step_id)` | single | Replay one failing step, propose a locator/wait/data patch (human-gated). |
| `triage_run(context_id)` | single | Classify each failure → Bug / Heal / Flaky / Environment. |
| `get_run_report(context_id, run_id=None)` | read-only | The persisted run report (per-env, per-scenario, oracle results). |
| `list_environments(context_id)` | read-only | The environments seen for this context and their last run state. |

**Pipeline seam** — the Executor slots in *after* `get_scenarios`, optional and read-model-friendly like
`evaluate_plan`:

![Pipeline seam: the existing linear pipeline (gather -> refine -> approve -> [evaluate_pack] -> define_plan -> approve_plan -> implement_plan -> get_scenarios, with approve/approve_plan as human gates and evaluate_pack an optional read-only gate) flows left to right; after get_scenarios an orange connector drops into the NEW execution stage — run_suite -> [triage_run / heal_step] -> get_run_report — which is the new EXEC A2A agent, optional and read-model-friendly like evaluate_plan. It re-enters TEV at [evaluate_plan], now execution-grounded (see section 6).](./exec-pipeline-seam.png)

---

## 2. Detailed flow

![Test Executor detailed flow: run_suite(context_id, env) -> step 0 RESOLVE ENV (pick target via JEV Choice, health-probe base_url, upsert env row) -> step 1 RUN deterministically with Playwright + behave, step binding via Playwright MCP a11y refs. Each step branches: PASS goes to step 2 MEASURE (coverage delta, flakiness x5, schema/status/auth conformance, mutation kills, per-scenario oracle); FAIL goes to step 3 TRIAGE (JEV Choice then LLM) which classifies into Actual Bug (record + stop), UI change (heal_step, through a HUMAN Yes/No gate, never a silent retarget), or Flaky/Env (quarantine x5). An accepted heal re-runs the patched step back at RUN, bounded by MAX_HEALS. MEASURE flows to step 4 PERSIST (run.json+traces to GCS, run row + oracle results to Postgres) then step 5 REPORT (get_run_report; real signals to TEV and the human).](./exec-flow.png)

A single `run_suite(context_id, env)` call drives the bounded inner loop above. Everything is checkpointed
to GCS under `context_id` so a Cloud Run kill **resumes** at the last completed scenario.

**Key properties of the flow:**

- **Discover-once, compile, heal-on-fail.** Step binding resolves against the *current* a11y tree; the
  resolved `ref` is cached deterministically. The LLM only re-engages on a `FAIL` that triage labels
  *UI-change*.
- **Self-heal is human-gated.** Every locator/wait/data patch a healer proposes is surfaced through the
  client's existing **Yes/No gate** — a silent retarget can mask a real regression. This is the same gate
  discipline the pipeline already enforces at `approve` / `approve_plan`.
- **Flakiness is a verdict, not a guess.** A step that oscillates is re-run ×5; JEV `noul("this test is
  flaky")` + the run history decide *quarantine* (still runs, no longer blocks) vs *real intermittent bug*.
- **Bounded.** `MAX_HEALS` per run and a per-scenario timeout keep the loop finite; exhaustion → record as
  unresolved and move on, never spin.
- **Resumable.** Each completed scenario is checkpointed; re-invoking `run_suite(context_id)` after a kill
  continues from the last checkpoint (resume-not-restart).

---

## 3. Implementation details

The built version is a **lean, home-grown** realization of this design — the heavy surveyed tools (§8) are
deferred behind the same seams. What ships is marked **[built]**; what the original survey proposed but is
not yet wired is **[deferred]**.

### 3.1 Execution backbone (Pillar 2) — **[built, leaner than surveyed]**

Rather than a Gherkin-runner + Playwright-MCP + Test-Agents stack, the agent **routes each scenario by its
declared `methodology`** (`runners.select_engine`) to one of three real engines, each returning an honest
`EngineResult` (`ran=False` = unbound, never a faked pass):

- **`ApiEngine`** — deterministic httpx: issues the scenario's structured `request` against `base_url` and
  checks conformance (status class + JSON validity + `expect_contains` oracle, and the OpenAPI oracle in
  §3.2). Supports **multipart file upload** (bytes from an inline base64 bank fixture — never a local path).
- **`LlmEngine`** — one LLM call translates an NL scenario → a structured request, then delegates to
  `ApiEngine`. Bounded by a per-run `EXEC_LLM_MAX` budget.
- **`BrowserEngine`** — a real **Playwright chromium** (`PlaywrightDriver`, `--no-sandbox`), driving a
  structured browser plan (`{url_path, steps, expect_text}`); an NL UI scenario is translated to that plan
  by one LLM call. Navigation is pinned to the run's `base_url` origin by the egress allow-list.
- **Execution is gated + polled.** `EXEC_RUNNER` = `stub` (default: record env + a placeholder run, no live
  system) | `auto` (route + run + aggregate). `run_suite` advances **one `EXEC_CHUNK` at a time**, returns
  `[state: in_progress]`, and the client re-polls to done — the same multi-turn contract as `implement_plan`.
- **[deferred]** Gherkin-`.feature` runner (`playwright-bdd`/`behave`), Playwright-MCP a11y binding,
  Test-Agents / Healenium discovery-and-heal, DOM/vision fallbacks — see §8.

### 3.2 API oracle (Pillar 3) — **[built: home-grown OpenAPI conformance; heavy fuzzers deferred]**

`openapi.py` is a dependency-light oracle (plain spec parsing + `jsonschema`, the `[exec]` extra — **not**
Schemathesis): per run it fetches the environment's `spec_url` (Spring's `/v3/api-docs` etc.), **same-origin
gated and byte-capped**, flattens `paths` → operations, matches the executed request to a spec operation
(exact then templated), and asserts **status-code + response-schema conformance** (`conformance_failures`).
Remote/`file://` `$ref` resolution is disabled (a tampered SUT spec cannot SSRF/read files). The spec also
**grounds the LLM translator** — it picks a real operation from a compact catalog instead of inventing a path.

- **[deferred]** the heavy fuzz/oracle layers the survey recommends: **Schemathesis** full conformance
  battery + property-based **Hypothesis** data, **RESTler**/RestTestGen stateful+security sequences,
  metamorphic + **differential** (multi-env, §4), **Applitools** visual, **Pact** contracts, mutation. These
  ride the same OpenAPI/codegraph surface when wired.

### 3.3 State, resume, and the trust boundary — **[built]**

- **Run state → GCS / the run ledger** under `context_id` (resume-not-restart): a chunked run checkpoints
  its cursor + partial results to `exec_run` and continues on re-invoke.
- **Env + run metadata → shared Cloud SQL Postgres** via `common.db.get_engine()` (§4) — no new datastore
  (falls back to an in-memory ledger offline).
- **Credentials [built]:** per-environment auth via `auth.py` — `bearer` (token from a NAMED env var),
  `bearer_fetch` (POST a same-origin token endpoint → JSON field → bearer), or `login` (a browser fill/submit
  plan). Secrets come from **named env vars** (Secret-Manager-injected), NEVER inline in `EXEC_ENVIRONMENTS`;
  the resolved value only ever reaches httpx `headers=` — the ledger records the auth **KIND** (`creds_ref`),
  never the value, and any inline userinfo in `base_url` is stripped before persist.
- **Egress [built]:** a per-run **allow-list** (`_same_site`) pins every request/navigation to the run's
  `base_url` **origin** (scheme + host + port) — the executor legitimately targets internal/localhost test
  envs, so this is an origin allow-list, **not** `common/net.host_blocked` (which would wrongly block those);
  it blocks metadata / `file://` / foreign-host / same-host-different-port pivots from scenario text. This is
  the security delta of the whole agent — the primary review surface (§9).

---

## 4. Multi-environment execution + the per-environment database

![Multi-environment execution and the per-environment database. The Test Executor's run_suite fans out to many target environments (dev, staging, a specific Cloud Run revision rev:abc123, a customer tenant); a new env becomes a new row on first sight (dynamic). Differential mode runs the same input against two environments and diffs the responses — consensus IS the oracle. Every run upserts its env and inserts one run row into the shared Cloud SQL Postgres (common.db.get_engine), which holds two new tables: exec_environment (id, context_id, name, base_url, revision, creds_ref = a Secret Manager path not the value, health jsonb, first/last_seen) and exec_run (id, context_id, environment_id FK, state, summary, signals, triage, trace_uri). GCS holds the heavy traces/screenshots; Postgres holds the queryable metadata plus a trace_uri pointer.](./exec-multienv-db.png)

**The requirement.** The Executor must run the same `.feature` across **multiple environments** (local /
dev / staging / a specific Cloud Run revision / a customer tenant) and **dynamically store each tested
environment's info to a database** — so runs are comparable across environments and over time, and so
**differential testing** (§3.2) has two sides to diff.

**The lazy-but-correct store: reuse the Postgres that is already there.** `common/db.py::get_engine()` is a
single async SQLAlchemy pool that dials Cloud SQL via the Python Connector (`TASK_DB_URL` / `DB_*`), and it
**already backs** the A2A `DatabaseTaskStore`, the ADK `DatabaseSessionService`, pgvector memory, and the
prompt store. The tested-environment DB is **two new tables on that same engine** — not a new datastore
(memory: *Task store on Cloud SQL*; handoff constraint: reuse the existing Postgres).

```sql
-- environment registry: one row per (context_id, environment) ever tested
CREATE TABLE exec_environment (
  id            uuid PRIMARY KEY,
  context_id    text NOT NULL,
  name          text NOT NULL,             -- 'dev' | 'staging' | 'rev:abc123' | 'tenant:42'
  base_url      text NOT NULL,
  kind          text,                       -- cloud-run | gke | local | tenant
  revision      text,                       -- image tag / git sha / Cloud Run revision
  creds_ref     text,                       -- Secret Manager path — NEVER the secret value
  health        jsonb,                      -- last probe: {ok, status, latency_ms, checked_at}
  first_seen    timestamptz DEFAULT now(),
  last_seen     timestamptz DEFAULT now(),
  UNIQUE (context_id, name)
);

-- run ledger: one row per run_suite invocation against one environment
CREATE TABLE exec_run (
  id             uuid PRIMARY KEY,
  context_id     text NOT NULL,
  environment_id uuid REFERENCES exec_environment(id),
  started_at     timestamptz DEFAULT now(),
  finished_at    timestamptz,
  state          text,                       -- in_progress | done | failed
  summary        jsonb,                      -- {passed, failed, healed, quarantined, flaky}
  signals        jsonb,                      -- coverage_delta, flakiness, conformance, mutation_kills
  triage         jsonb,                      -- per-scenario Bug/Heal/Flaky/Env verdicts
  trace_uri      text                        -- gs://…/context_id/run_id/  (heavy artifacts stay in GCS)
);
```

> **[status — built vs designed].** Both tables ship (`store.py`), on the shared engine, with two pragmatic
> differences from the DDL above: ids are `text` (not `uuid`) and the run status column is `status`
> (`in_progress | done`). `exec_environment` carries `kind`/`revision`/`creds_ref`/`health` as designed
> (scaffolding for the deferred features). **Deferred:** JEV-`Choice` env-selection (step 1 below — today
> `env` is passed explicitly / resolved from `EXEC_ENVIRONMENTS`, else the `EXEC_BASE_URL` default) and
> **differential** cross-env mode (step 4).

**How the AI runs across environments.**

1. **Choose the target.** The client passes `env` (a name in `EXEC_ENVIRONMENTS`, resolving its `base_url` +
   `auth`), else the `EXEC_BASE_URL` single-target default. *[deferred]* agent-side selection via a **JEV
   `Choice`** over the `exec_environment` rows (§5) — "which env is healthiest / most representative?".
2. **Register / refresh.** Health-probe `base_url`; **upsert** the `exec_environment` row (`last_seen`,
   `health`). New environment → new row, *dynamically*, on first sight — the DB grows as environments are
   tested, no pre-registration.
3. **Run + record.** Execute the suite; write one `exec_run` row with the run summary, the real **signals**
   (§6), and per-scenario triage. Heavy artifacts (traces, screenshots) stay in **GCS**; Postgres holds the
   queryable metadata and a `trace_uri` pointer — the same GCS-heavy / SQL-light split the rest of the
   system uses.
4. **Differential across envs.** With ≥2 `exec_run` rows for the same `context_id` on different
   environments/revisions, the oracle stack runs **differential mode** (§3.2): same input, two envs, diff
   the responses — any divergence is a regression, and *consensus is the oracle* (no ground truth needed).
   This is the concrete payoff of storing every tested environment: the second environment *is* the oracle
   for the first.

**Why not a new datastore.** A Cloud Run redeploy once wiped in-flight GCS memory-bank state (memory:
*Test-plan scenario-generator gotchas*); the task store moved to Cloud SQL precisely so run/task state
survives. Putting the env ledger anywhere else re-opens a durability gap the system already closed. One
engine, one pool, two tables.

---

## 5. JEV judge & evaluation

![JEV judge and the cascade. Runtime state (a trace, or the env registry) goes to the JEV DecisionProvider (choice/score/noul, ~150ms and ~free); if its calibrated confidence is at or above a THRESHOLD (~90% of calls) it returns a typed Verdict (value, probs, confidence) directly; otherwise (~10% hard tail) it falls through to the existing LLM judge, whose code is unchanged. The Executor's decision sites map to primitives: Triage (Bug/Heal/Flaky/Env) → Choice/Noul; Heal-accept 'patch preserves intent' → Noul; Flakiness 'non-deterministic' → Noul + history; Env selection / run-health → Choice/Score. With TPD_DECISION_BACKEND unset, get_decision_provider() returns None and every caller keeps its LLM path; the deterministic scorers stay JEV-free (I8).](./exec-jev-cascade.png)

The Executor makes a stream of **typed decisions** at runtime — *is this failure a real bug or a UI change?
should this heal be accepted? is this test flaky? which environment do I target?* Those are **exactly** what
the **JEV `DecisionProvider`** port (added beside `ModelProvider` — `common/adk/providers/decision.py`) is
for. See [`RESEARCH-jev-in-test-agent-v2.md`](./RESEARCH-jev-in-test-agent-v2.md).

**The port (already in-tree, default OFF).** `DecisionProvider` exposes three primitives returning a typed
`Verdict(value, probs, confidence)`:

| Primitive | Signature | Executor use |
|-----------|-----------|--------------|
| **Choice** | `choice(state, options, instructions) → Verdict` | Pick the **target environment** from the registry; route a failure to a triage bucket. |
| **Score** | `score(state, instructions, levels) → Verdict` | Grade **run health** / heal-risk on an ordinal scale (0–1 via `score01`). |
| **Noul** | `noul(state, statement) → Verdict` | Yes/no judgments: "*this failure is a product bug*", "*this test is flaky*", "*this heal preserves intent*". `value` is a bool, `probs` its distribution. |

**The cascade (the important part).** JEV **fronts** the LLM, it never replaces it — strictly additive:

```
v = decision.noul(trace_state, "this failure is a real product bug")   # JEV: ~150ms, ~free
if v.confidence >= THRESHOLD:      # ~90% of calls — fast typed path
    verdict = v.value
else:
    verdict = llm_triage(trace_state)   # ~10% hard tail — existing LLM judge, unchanged
```

`get_decision_provider()` returns `None` when `TPD_DECISION_BACKEND` is unset → **every call site keeps its
existing LLM path**. Worst case = today's behaviour. `TEV_NOUL_THRESHOLD` (0.5 default) is the semantic
accept cut; calibrate the confidence gate against TEV's golden sets before trusting the fast path.

> **[status].** Only the **triage** site is wired (`runner.triage` → `_jev_bucket` uses
> `DecisionProvider.choice` over the four buckets, default OFF via `TPD_DECISION_BACKEND`, degrading to the
> deterministic `classify_failure` heuristic). Heal-accept, flakiness×5, and env-selection are **[deferred]**
> (heal is a plain LLM propose-and-verify; there is no ×5 flakiness re-run or JEV env pick yet). *Gotcha:*
> the `choice` primitive is what triage needs — it must stay on the port even though it has a single caller.

**Where JEV lands in the Executor:**

| Site | Primitive | Replaces |
|------|-----------|----------|
| **Triage classifier** (Bug / Heal / Flaky / Env) | Choice / Noul | an LLM call per failure over the trace |
| **Heal-accept** ("*patch preserves scenario intent*") | Noul | LLM judgment before surfacing the Yes/No gate |
| **Flakiness** ("*non-deterministic, not a real fail*") | Noul + run-history | a heuristic threshold |
| **Env selection / run-health** | Choice / Score | static "use dev" |

**Invariant kept (I8).** The **deterministic** scorers stay LLM-free and JEV-free. JEV only touches the
Executor's **runtime judgments** and TEV's **opt-in judged tiers** — never the deterministic product path
(`evaluate_pack` / `evaluate_plan` / `metrics/*`). The Executor's real signals (§6) are *measurements*, not
judgments; JEV classifies what to *do* with a failure, not whether a number is correct.

---

## 6. How it extends the Test-Evaluation (TEV) stage

![How the Executor extends TEV. Left, TODAY: deterministic proxies with no run — metrics/oracle.py oracle_strength and metrics/mutation.py fault_class_coverage both feed fault_detection = 0.30 (dashed, inactive). Right, WITH THE EXECUTOR: real execution signals — real mutation score (mutmut/PIT/Stryker, mutants killed), executed coverage delta, schema/status/auth conformance pass-rate, and flakiness x5 from the run ledger — feed the same fault_detection = 0.30 term (same weight, real input), sourced from the Test Executor's exec_run.signals, plus a new TEV tool evaluate_run(context_id) and benchmarking across environments. The TPS formula (0.30 fault_detection + 0.25 brief_groundedness + 0.20 coverage + 0.15 oracle_strength + 0.10 trajectory) is unchanged — only fault_detection's source improves from proxy to real run.](./exec-tev-extension.png)

> **[status — entirely deferred].** None of §6 is built yet: `evaluate_run`, a `metrics/execution.py`, the
> `fault_detection` source-swap, and execution-grounded benchmarking do not exist. The Executor persists
> real per-run **signals** to `exec_run` today, but TEV does not yet read them — this is the next seam to
> wire once the run signals stabilize.

TEV today scores the pipeline output **without ever running it**, so several of its terms are honest
**proxies** waiting for exactly this agent. The Executor's job on the TEV side is to **retire the proxies**.

**The proxies TEV currently ships** (`src/test_evaluation`):

- `TPS_WEIGHTS` = `fault_detection 0.30 · brief_groundedness 0.25 · coverage 0.20 · oracle_strength 0.15 ·
  trajectory 0.10` (`metrics/tps.py`).
- `metrics/oracle.py::oracle_strength` — "*deterministic proxy for mutation*": grades each step's `expected`
  string strong/medium/weak **without running anything** ([`RESEARCH-test-oracle.md`](./RESEARCH-test-oracle.md)).
- `metrics/mutation.py::fault_class_coverage` — "*fault-class-coverage PROXY (real mutation is gated on the
  execution stage)*": counts whether a fault class was *aimed at*, not whether a test *kills* it.

**What the Executor feeds back:**

| TEV term / metric | Today (proxy) | With the Executor (real) |
|---|---|---|
| `fault_detection` (0.30 — the heaviest weight) | `oracle_strength` + `fault_class_coverage`, both static | **real mutation score** (mutmut / PIT / Stryker run against the suite) — mutants *killed*, not *aimed at* |
| `coverage` (0.20) | AC-coverage recall + matrix completeness, from the plan text | **executed coverage delta** — lines/branches the run actually hit |
| oracle strength (0.15) | classifier over `expected` strings | **stays** as its own signal, now *cross-checked* against which oracles actually caught injected faults |
| *(new)* schema/status/auth conformance | — | Schemathesis battery pass-rate per scenario |
| *(new)* flakiness×5 | — | non-determinism rate from the run ledger |

**Mechanically, minimal surface change on TEV:**

- **A new metric module** `metrics/execution.py` (or the real body of `metrics/mutation.py`) reads the
  `exec_run.signals` row and returns real mutation / coverage-delta / conformance / flakiness scores.
- **`fault_detection` swaps its source**: when an `exec_run` exists for the `context_id`, the composite uses
  the real mutation score; otherwise it falls back to today's proxy. Same weight, better input — the TPS
  formula is unchanged, only the term's provenance improves.
- **New TEV bridge tool** `evaluate_run(context_id)` alongside `evaluate_pack` / `evaluate_plan`, and the
  existing `benchmark_run` / `compare_benchmarks` now compare **execution-grounded** runs across
  environments (join on `exec_run.environment_id`).
- **The assured loop closes.** The TPD assured loop's ②–③ *MEASURE* step is today stubbed by a judge-rubric
  score ([`RESEARCH-tpd-assured-generation.md`](./RESEARCH-tpd-assured-generation.md), "*honest gap*"). The
  Executor supplies the real `builds ∧ passes×5 ∧ raises coverage ∧ kills mutant` gate — the generation
  loop stops trusting a proxy and starts gating on a run.

Net: TEV keeps its weights and its deterministic, LLM-free spine (I8); the Executor upgrades **the inputs to
the two proxy terms** from "what the plan *says*" to "what a run *did*."

---

## 7. Roadmap (Executor phases)

→ [`agentic-qa-enhancement-roadmap.png`](./agentic-qa-enhancement-roadmap.png) (full P0–P5, both agents)

Each phase is independently shippable. **Status:** ✅ built · ◑ partial · ⏸ deferred.

| Phase | What | Pillar | Status (2026-09-24) |
|-------|------|--------|---------------------|
| **P1 — execution backbone** | run the scenarios; run state → the ledger; env + run rows → Postgres. | 2 | ✅ **built** — as the 3-engine route-by-`methodology` design (§3.1), not the `.feature`/Playwright-MCP stack. New A2A service + 2 tables live; multi-env + auth + file-upload shipped. |
| **P3 — real oracles** | contract-conformance; metamorphic + differential (multi-env); stateful/security. | 3 | ◑ **partial** — home-grown OpenAPI status + response-schema conformance built (`openapi.py`); Schemathesis/RESTler/Hypothesis, metamorphic, and differential deferred. |
| **P5 — self-heal & mutation** | heal + JEV triage/quarantine; real mutation score feeds TEV `fault_detection`. | 1,2 | ◑ **partial** — LLM propose-and-verify `heal_step` (human-gated) + JEV/heuristic triage built; flakiness×5/quarantine, a healer library, mutation, and the TEV `fault_detection` feed (§6) deferred. |

**Constraints to respect (from this system's history):**
- **Off the request path** — kick off a job, poll, persist; never block the Cloud Run request/liveness timeout.
- **Resume, not restart** — checkpoint per scenario to GCS keyed by `context_id`.
- **Human owns the final gate** — heals/quarantines are surfaced Yes/No, never silent.
- **Ground in the codegraph** — producer/consumer inference and focal targeting read the graphify codegraph.
- **Reuse the Postgres** — env/run ledger on `common.db.get_engine()`, not a new datastore.
- **Sandbox the creds/egress** — the Executor's trust boundary is the biggest security delta in the system.

---

## 8. Reference — tooling landscape (compact)

Point-in-time (≈ Sept 2026); maintenance flags in §9.

| Layer | Pick | Why |
|-------|------|-----|
| Runner | **Playwright** + `playwright-bdd` / `behave` | runs the exported Gherkin unchanged |
| Step binding | **Playwright MCP** | a11y `ref`s, Claude-native, deterministic-mappable |
| UI discovery / heal | **Playwright Test Agents** (`--loop=claude`), **Healenium** | Planner/Generator/Healer; DOM-fingerprint heal |
| Vision fallback | browser-use · Skyvern · Midscene | canvas / cross-origin where a11y fails |
| API oracle | **Schemathesis** (spec = generator *and* oracle) | conformance battery for free off OpenAPI |
| Stateful / security | **RESTler** · RestTestGen | producer/consumer sequences + security checkers |
| Property data | **Hypothesis** (via Schemathesis) | boundary/malformed inputs, shrunk reproducers |
| Mutation | **mutmut** / **PIT** / **Stryker** | the *quality* number for TEV `fault_detection` |
| Visual oracle | Applitools Eyes | perceptual baseline for appearance regressions |
| Contracts | **Pact** | consumer-driven contracts where codegraph shows cross-service use |
| Reference loops | SWE-agent / Aider / OpenHands | the run→observe→fix agentic template |

**Glossary** (self-healing locator, a11y grounding, metamorphic / differential testing, the oracle problem,
stateful fuzzing, quarantine, trace/replay) is in [`RESEARCH-test-oracle.md`](./RESEARCH-test-oracle.md) and
the companion assured-generation report — not repeated here.

---

## 9. Caveats & source hygiene

- **New trust boundary.** Unlike the read-only KGA/TPD/TEV, the Executor holds test-env credentials and
  makes live calls / drives a browser — the biggest security delta of this agent. Sandbox it; store secret
  *references*, not values; allow-list egress per run. This is the primary review surface.
- **Maintenance flags.** **Dredd** (archived Nov 2024) and **Spring Cloud Contract** (archived) — prefer
  **Schemathesis** and **Pact**. **jqwik** in maintenance mode. Octomind "discontinued for new customers"
  is single-sourced/unverified. Qodo Cover "no longer maintained (~2025)" — vendor/fork, don't depend on
  upstream.
- **Vendor claims** (mabl "80–99% heal", Skyvern WebBench 64.4%) are self-reported — directionally
  credible, not independently verified here.
- **JEV calibration** is per-model and early-access — calibrate the cascade threshold on TEV goldens before
  trusting the fast path; re-check on any JEV model update. Data residency (JEV region vs `europe-west6`)
  before sending customer state.
- Star counts / versions are point-in-time (≈ Sept 2026).

### Primary sources (selection)
Playwright Test Agents https://playwright.dev/docs/test-agents · Playwright MCP
https://github.com/microsoft/playwright-mcp · browser-use https://github.com/browser-use/browser-use ·
Skyvern https://github.com/Skyvern-AI/skyvern · Healenium https://github.com/healenium/healenium ·
Schemathesis https://github.com/schemathesis/schemathesis · RESTler
https://github.com/microsoft/restler-fuzzer · Hypothesis https://github.com/HypothesisWorks/hypothesis ·
Pact https://docs.pact.io · Metamorphic testing survey https://dl.acm.org/doi/10.1145/3143561 · Meta ACH
https://arxiv.org/abs/2501.12862 · A2A https://a2a-protocol.org · MCP https://modelcontextprotocol.io

---
*Rewritten 2026-09-23 from the earlier Pillars-2&3 survey into a design spec; **reconciled with the shipped
`src/test_executor/` code 2026-09-24** (implementation-status markers throughout — the built agent is a
leaner, home-grown realization of this design; the heavy surveyed tools in §8 remain deferred).
Generation-side pillars (1 & 4) in [`RESEARCH-tpd-assured-generation.md`](./RESEARCH-tpd-assured-generation.md);
scoring in [`RESEARCH-tpd-evaluation-adk-testsuite.md`](./RESEARCH-tpd-evaluation-adk-testsuite.md). Diagrams
authored in Excalidraw; regenerate PNGs with the repo's `render_excalidraw.py`.*
