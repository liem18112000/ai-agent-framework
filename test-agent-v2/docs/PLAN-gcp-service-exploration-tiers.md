# GCP Service Exploration — Tiers 5/6/7 for the Self-Exploration Loop

**Purpose.** Extend the Knowledge-Gathering Agent's **self-exploration loop**
with a **runtime/operational** source: the live Google Cloud estate. Today the loop reaches four
*document* tiers (memory → Atlassian search → external web → external LLM). It has never looked at
**what is actually deployed and running**. This plan adds a **GCP-explore sub-agent** that grounds the
test basis in production reality by doing three things, in order:

| New tier | Responsibility | Rides which existing seam |
|---|---|---|
| **Tier 5 — Discover** | Enumerate the *prominent* services/deployments across **every env** (`dev`, `dev-staging`, `performance`, `test`, `prod`) for **GKE**, **Cloud Run**, and **managed services** (Cloud SQL, Pub/Sub, …). | New **seed producer** in `expansion_round` → promotes `gcpsvc:` node ids |
| **Tier 6 — Inspect logs** | For each discovered service, read Cloud Logging over an **expanding window** — 7 → 14 → 21 → 28 days — widening only until *enough* signal is captured. | New **`NodeFetcher`** for the `gcpsvc:` kind (the "fetch" seam) |
| **Tier 7 — Relate** | Infer how the services **communicate** (who calls whom, over what) and emit those as graph edges. | The fetcher emits **`LinkRecord`s** → in-scope → the existing crawl **walks the service graph** |

> **Diagram (open in Excalidraw, PNG renders inline):**
> - GCP Service Exploration — [`gcp-service-exploration-tiers.excalidraw`](./gcp-service-exploration-tiers.excalidraw) · [`.png`](./gcp-service-exploration-tiers.png)

House style matches the sibling reports: TL;DR + principle, glossary, current anatomy, target
architecture, tier-by-tier design, phased roadmap, and the constraints this system's own history imposes.

---

## 0. TL;DR — the one gap and the one principle

**Where we are.** The self-exploration loop turns a thin Jira seed into a grounded pack by fanning out
across *documents*: prior memory, Jira/Confluence search, web pages, and LLM-suggested leads
(`expansion_round` → promote seeds → `crawl` → fetch → follow links → converge). Every node kind it knows
(`jira`, `confluence`, `bitbucket`, `codegraph`, `external-web`) is a **document**.

**The gap.** A test basis built only from documents describes the system **as designed**, never **as
running**. The pack cannot answer: *Which services actually implement this ticket? In which envs are they
deployed? What errors do they throw today? Which downstream services do they call?* That operational
truth is the difference between a plausible test plan and one that exercises the real failure modes
(the memory notes already name this — codegraph grounding gives *structure*, not *execution depth*).

**The principle (the tier-5/6/7 rule).** Mirror the loop's existing rule — *"don't stop at the seed"* —
into the infrastructure plane:

> **From the ticket's terms, discover the services that actually run it across every environment; read
> each one's recent logs, widening the window only until the signal is enough, not to a fixed depth; and
> follow the communication edges the logs reveal to the neighbouring services — the same way the crawl
> follows a Jira issue-link. Every service and every edge must cite a real GCP resource or log field.
> The sub-agent prioritizes and distills; it never invents a service or an edge.**

That is Retrieval-Augmented exploration extended to the **live estate**: the GCP API is the authoritative
source (like Jira), the deterministic crawl stays the executor, and the LLM is a *planner/distiller*, never
a source of truth — exactly the split already used for the `hypothesize` / `leads` planners.

**Tier numbering.** The existing loop counts four source tiers (1 internal memory, 2 Atlassian search,
3 external web, 4 external LLM). This plan adds **5 = discover**, **6 = logs**, **7 = relate**.

---

## 1. Concepts & terms (glossary)

| Term | Definition | Why it matters here |
|---|---|---|
| **Env matrix** | The five deployment environments — `dev`, `dev-staging`, `performance`, `test`, `prod` — each resolved to a concrete `(project, region, namespace)` tuple by a single config map. | "Across all envs" must be *data*, not branching logic. One dict maps env → where to look; adding an env is a one-line edit. |
| **Prominent service** | A deployed workload that is relevant to the ticket *and* actually live (has traffic / recent revisions / recent logs), ranked above the long tail of dormant services. | "Prominent" bounds Tier 5: we promote the top-N ranked services, not every asset in the org. |
| **`gcpsvc:` node** | A first-class knowledge-graph node for one deployed service in one env: `gcpsvc:<env>/<platform>/<name>` (e.g. `gcpsvc:prod/run/luz-thumbnail`, `gcpsvc:dev/gke/luz-docs`, `gcpsvc:test/managed/cloudsql-taskstore`). | Makes services fetchable + follow-able by the *unchanged* crawl. The canonical id is a stable dedup key, same role as `jira:LUZ-1`. |
| **Expanding log window** | Read logs for the last 7 days; if signal is insufficient, widen to 14, 21, 28; stop at the first window that yields *enough* (or at the 28-day cap). | The adaptive-breadth analog of the crawl's adaptive depth. A fixed lookback under- or over-reads; the window is the marginal-yield stop applied to *time*. |
| **"Enough" gate** | The stop condition for the window: ≥ *k* distinct error/log signatures **or** ≥ *m* distinct outbound dependency edges **or** ≥ *n* total in-scope entries — whichever first. | Bounds cost and latency. Same shape as the crawl's convergence stop; without it, every service reads 28 days of logs every time. |
| **Communication edge** | An inferred `A → B` relationship: service A calls service B (HTTP host, gRPC target, DB instance, Pub/Sub topic, audience claim, trace span). | Tier 7. Emitted as `LinkRecord`s so the frontier walks A → B → C without any new traversal code. |
| **Grounding gate (infra)** | An edge or service enters the pack only if backed by a real GCP field (a resolved resource, a log line, a config value). LLM-suggested edges that can't be corroborated are dropped or demoted to "unconfirmed". | The single highest-risk rule. Skipping it injects a hallucinated topology into the test basis. Direct port of the loop's Tier-3b lead-grounding gate. |
| **Read-only reach** | Every GCP call is a *viewer* operation (list assets, read logs, describe services). No mutation, ever. | Security boundary. The agent's SA gets only `*.viewer` roles; a gather can never change the estate it inspects. |
| **Cloud Asset Inventory (CAI)** | `cloudasset.searchAllResources` — one API that lists resources of many types across all projects in a folder/org. | The cheapest single call to enumerate "everything deployed across all envs". Per-platform list APIs are the fallback when CAI isn't available. |

---

## 2. Where we are — the loop's anatomy & the exact seams

The plan rides three seams that already exist. Nothing about the crawl changes.

### 2.1 The three extension points (from the current code)

1. **Seed-producer seam — `expansion_round()`** (`gather/explore/expand.py`). Runs one pre-crawl fan-out
   and returns `(new_seeds, md_blocks)`. Every tier is just a function that returns canonical node ids to
   promote and a markdown block for the reply. **Tier 5 is a new producer here.**
2. **Fetcher seam — the `NodeFetcher` registry** (`gather/crawl/fetch/base.py`). One subclass per node
   `kind`, auto-registered by its `kind` prefix; `fetch_node` dispatches on the id prefix with zero changes.
   Adding a source = drop in a subclass + import it. **Tier 6 is a new `GcpServiceFetcher(kind="gcpsvc")`.**
3. **Link-follow seam — `crawl()` + `_fetchable()`** (`gather/crawl/crawl.py`). A node's in-scope
   `LinkRecord`s are pushed to the frontier and fetched, bounded by `depth / max_nodes / max_seconds`.
   **Tier 7 needs only that `gcpsvc:` edges are `in_scope` and `gcpsvc` is `_fetchable` — the crawl then
   walks the service graph for free.**

### 2.2 The planner pattern to copy

The two existing planners (`hypothesize`, `leads`) are ADK `LlmAgent`s with a Pydantic `output_schema`,
run by `GatherAgent._run_planner` **before** `expansion_round`; each degrades to a no-op when Vertex is
unconfigured (`_run_planner` swallows the failure). **The GCP-explore sub-agent is a third planner of
exactly this shape** — it plans *which* envs/services matter and *distills* what the deterministic reach
returns; the reach itself is plain, offloaded GCP calls.

### 2.3 What must NOT change (invariants inherited from history)

- **The deterministic crawl stays** — new tiers feed it seeds and edges; they never replace `crawl.py`.
- **The human gate stays** — `refine → approve` still decide what becomes the test basis. Every service
  node and edge carries provenance so a human can prune.
- **One LLM budget discipline** — the sub-agent is *one* planner call (like `hypothesize`), not a
  per-service call. Memory: *serial blocking model/API calls in an async handler blew Cloud Run's
  liveness/request timeout*. All GCP I/O is offloaded to threads and bounded.
- **No silent truncation** — every cap hit (max services, window at 28 d, dropped edges) is logged and
  surfaced in the reply, per the standing rule.

---

## 3. Target architecture — the GCP-explore sub-agent

> **Diagram (open in Excalidraw, PNG renders inline):**
> [`gcp-explore-subagent-architecture.excalidraw`](./gcp-explore-subagent-architecture.excalidraw)
> · [`.png`](./gcp-explore-subagent-architecture.png) — the sub-agent plans/ranks **once**; the
> deterministic crawl then drives tiers 6 & 7 per node and converges.

```
                       ticket terms (from SeedProbe + hypothesize)
                                        │
                          ┌─────────────▼─────────────┐
                          │   GCP-explore sub-agent    │   (one LlmAgent; degrades to
                          │   plan envs · rank · distil │    name-match heuristic w/o Vertex)
                          └─────────────┬─────────────┘
      Tier 5 DISCOVER (seed producer)   │  reach = deterministic, read-only, to_thread
   ┌──────────────────────────────────▼──────────────────────────────────┐
   │  Cloud Asset Inventory searchAllResources over folder/org            │
   │  → filter to run / gke / managed types, across env→(project,region)  │
   │  → rank by (term match ∪ liveness) → promote top-N  gcpsvc:  seeds   │
   └──────────────────────────────────┬──────────────────────────────────┘
                                       │ extra_seeds
                          ┌────────────▼────────────┐
                          │  existing crawl()        │   frontier, bounded, concurrent
                          └────────────┬────────────┘
      Tier 6 LOGS (NodeFetcher)        │ fetch_node("gcpsvc:prod/run/luz-thumbnail")
   ┌──────────────────────────────────▼──────────────────────────────────┐
   │  Cloud Logging read, window 7→14→21→28d until "enough" gate trips    │
   │  → distil Note: purpose · error signatures · routes · dependencies   │
   │  → REDACT payloads (no secrets/PII into the note)                    │
   └──────────────────────────────────┬──────────────────────────────────┘
      Tier 7 RELATE (LinkRecords)      │ emits gcpsvc:A → gcpsvc:B edges
   ┌──────────────────────────────────▼──────────────────────────────────┐
   │  edges from log fields + config + trace  (grounding gate: real field)│
   │  → in-scope gcpsvc edges pushed to frontier → crawl fetches B → …    │
   │  → converges by depth / max_nodes / max_seconds                      │
   └─────────────────────────────────────────────────────────────────────┘
```

The sub-agent is invoked once (Tier 5 planning + ranking); Tiers 6 and 7 are pure fetcher work that the
crawl drives per node. The service graph converges on the same budget knobs the document crawl uses.

---

## 4. Tier 5 — Discover services across every env

**Goal.** From the ticket terms, list the *prominent* deployed services across `dev / dev-staging /
performance / test / prod` for **GKE**, **Cloud Run**, and **managed services**, and promote the top-N to
`gcpsvc:` seeds.

### 4.1 The env matrix (config, not code) — per-provider, fully config-driven

Each **`CloudProvider` adapter owns its own** env→coordinates map; **no vendor values are compiled into
source** (`ENV_MATRIX` ships empty). The GCP adapter reads its map from config, so the map below is an
**EXAMPLE only** (it lives in `.env.example` + `deployments/test-agent-v2/gcp-env-matrix.example.json`,
not in `.py`):

```jsonc
// EXAMPLE — the real map is config, never source. Per env: project+region required; cluster+namespace
// needed for k8s discovery/log filters. GCP coordinates = project · region · cluster · namespace.
{
  "dev":  {"project": "klara-nonprod", "region": "europe-west6", "cluster": "klara-nonprod", "namespace": "dev"},
  "prod": {"project": "klara-prod",    "region": "europe-west6", "cluster": "klara-prod",    "namespace": "prod"}
}
```

Two config sources (precedence): **`KGA_GCP_ENV_MATRIX`** (inline JSON, primary) → else
**`KGA_GCP_ENV_MATRIX_FILE`** (a mounted JSON file, better for a big multi-env/cluster map). Neither set
→ the adapter has **zero envs → the tier no-ops** (safe: opt-in). Malformed/partial entries are skipped
(logged once), never raised. Adding `sandbox` is one config entry; a different Azure/AWS adapter reads
its own map the same way (its record holds whatever coordinates that provider needs to locate an env).

### 4.2 The reach — one API, per-platform fallback

**Primary: Cloud Asset Inventory.** One `searchAllResources(scope=folder/…, assetTypes=[…])` call per
env-project enumerates all three platform families:

| Platform | Asset type(s) |
|---|---|
| Cloud Run | `run.googleapis.com/Service` |
| GKE | `container.googleapis.com/Cluster` + workloads via `k8s.io/Deployment`, `k8s.io/StatefulSet` |
| Managed | `sqladmin.googleapis.com/Instance`, `pubsub.googleapis.com/Topic`, `redis.googleapis.com/Instance`, `cloudtasks.googleapis.com/Queue`, … (config-driven allow-list) |

**Fallback (CAI not enabled / no org-level scope):** per-platform list clients —
`run_v2.ServicesClient.list_services`, `container_v1.list_clusters`, `sqladmin`/`pubsub` list — iterated
over the env matrix. Same output shape. Each platform failing independently degrades to the others (the
tier-2 pattern: *one source failing must not kill the rest*).

Every discovered asset carries its **full resource path** as provenance
(`//run.googleapis.com/projects/klara-prod/locations/europe-west6/services/luz-thumbnail`).

### 4.3 Ranking — what "prominent" means

Discovery can return hundreds of assets. The sub-agent (or its heuristic fallback) scores each and keeps
the top-N (`KGA_GCP_MAX_SERVICES`, default 8):

```
score(service) =  w1 · term_match(name, labels ; ticket_terms)     # relevance
                + w2 · liveness(recent_revisions | recent_logs)     # actually running
                + w3 · env_weight(prod > test > perf > staging > dev)  # closer to reality
```

- `term_match` reuses the loop's existing salient-token matcher (`salient_tokens`) — no new NLP.
- `liveness` is a cheap signal already available from the asset (update time / revision count); a service
  with zero recent activity is dormant, not prominent.
- The **LLM's only job** here is to *re-rank and cluster* the candidate list against the ticket intent
  (e.g. "these three thumbnail services are the same logical service across envs"). It **cannot add** a
  service that discovery didn't return — the grounding gate. With no Vertex, the numeric score alone ranks.

### 4.4 Output

Top-N services → `gcpsvc:<env>/<platform>/<name>` ids appended to `extra_seeds` (exactly like
`atlassian_search_seeds`), plus a markdown block listing what was found per env and what was capped.

---

## 5. Tier 6 — Inspect logs with an expanding window

**Goal.** For each `gcpsvc:` node the crawl fetches, read Cloud Logging over an **expanding time window**
and distill it into a Note.

### 5.1 The `GcpServiceFetcher`

A `NodeFetcher(kind="gcpsvc")`. `fetch(client, ident, nid, scope)` parses `ident = "<env>/<platform>/<name>"`,
resolves the env tuple, and reads logs with a platform-appropriate filter (reusing the exact filters the
org skills already use):

- Cloud Run → `resource.type=cloud_run_revision AND resource.labels.service_name=<name>`
- GKE → `resource.type=k8s_container AND resource.labels.container_name=<name> AND …namespace_name=<ns>`
- Managed → resource-type-specific (`cloudsql_database`, `pubsub_topic`, …)

### 5.2 The expanding window (the heart of Tier 6)

```python
WINDOWS = (7, 14, 21, 28)   # days; KGA_GCP_WINDOWS overrides
for days in WINDOWS:
    entries = await asyncio.to_thread(read_logs, env, name, platform, days, cap=MAX_ENTRIES)
    signal = summarize_signal(entries)          # error sigs, routes, dep edges, count
    if enough(signal):        # ≥k error sigs OR ≥m dep edges OR ≥n entries
        break
    log.info("gcpsvc %s: %dd window insufficient (%s) — widening", nid, days, signal.brief())
# else: reached 28d cap — record the shortfall as a gap, never silently
```

- **Read-only, bounded, off the event loop.** `read_logs` is the sync Cloud Logging client wrapped in
  `asyncio.to_thread` (memory: sync GCS/Vertex on the loop = Cloud Run liveness death). Entry count is
  capped (`MAX_ENTRIES`, default 2000, matching the skills' `LIMIT`); severity defaults to `WARNING`+ to
  keep volume down, widening to all severities only if the window is starved.
- **"Enough" is marginal-yield on time**, not a fixed lookback — the same convergence principle the crawl
  applies to depth, applied to the window.
- **Concurrency** is inherited: the crawl already fetches each depth level concurrently under a semaphore,
  so N services' windows expand in parallel, not serially.

### 5.3 Distill + redact

The window's entries become the Note `synopsis`:

- **Purpose** — top request routes / handler names / operation types.
- **Health** — the distinct error/exception signatures + their counts (dedup by normalized message, not
  raw lines — the memory bank must not fill with 2000 near-identical stack traces).
- **Dependencies** — the outbound targets seen (feeds Tier 7).

**Redaction is mandatory** (security, non-negotiable): log bodies routinely carry tokens, PII, and
connection strings. The distiller strips anything matching secret/PII patterns and keeps *signatures and
counts*, never raw payloads. Nothing sensitive enters the persisted Note.

---

## 6. Tier 7 — Relate: how the services communicate

**Goal.** Turn each service's logs+config into `A → B` communication edges, and let the crawl walk them.

### 6.1 Where edges come from (each cites a real field — the grounding gate)

| Signal source | Edge evidence | `origin` |
|---|---|---|
| **Log fields** | outbound HTTP host, gRPC `:authority`, DB host/instance, Pub/Sub topic in the payload metadata, `httpRequest.referer`, JWT `aud` | `gcp-log` |
| **Config** | Cloud Run env vars holding a sibling service URL, GKE `Service` DNS (`svc.namespace.svc.cluster.local`), VPC connector targets | `gcp-config` |
| **Trace** | Cloud Trace spans that share a trace-id across two services in one request (the strongest, cheapest topology signal) | `gcp-trace` |

Each becomes `LinkRecord(source_id="gcpsvc:prod/run/A", url=<resource>, type="gcp-edge",
canonical_url="gcpsvc:prod/run/B", origin="gcp-log", in_scope=True)`. An edge with no resolvable target
resource is **dropped or demoted to a recorded-only "unconfirmed" edge** — never promoted. The LLM may
*label* an edge ("A publishes billing events to B") but may not *create* one without a field behind it.

### 6.2 The crawl walks the graph for free

Because `gcpsvc` edges are `in_scope` and `gcpsvc` is added to `_fetchable`, the existing loop pushes B
onto the frontier, fetches B's logs (Tier 6 again), discovers B's edges (Tier 7 again), and converges when
`depth` / `max_nodes` / `max_seconds` are hit — **identical machinery to following a Jira issue-link**.
This is the whole reason to model services as nodes and communication as links: Tier 7 needs almost no new
traversal code, only edge-extraction.

### 6.3 Result

The pack gains a **live service-communication subgraph** rooted at the services that implement the ticket:
who they are, per env; what they log; and how they talk to each other — each fact traceable to a GCP
resource or log line. That is the operational grounding the document tiers can't provide.

---

## 7. Wiring — the minimal diff

Everything below is additive; no existing behaviour changes.

> **The reach is a swappable port.** Tiers 5/6/7 ride a **`CloudProvider` port** (`common/cloud/`), the
> same ports-and-adapters convention as `ModelProvider` / `ObjectStore` / `VectorStore` / `Embedder`. The
> **GCP adapter** (`GcpCloudProvider`) is the only implementation today; Azure/AWS are future adapters.
> Everything neutral (node model, ranking, expanding-window loop, "enough" gate, redaction,
> edge-derivation + grounding gate) lives in the shared layer — only the *reach* (discover + read-logs)
> is per-provider. Modalities are **provider-neutral**: `serverless` (Cloud Run · Lambda · Functions),
> `k8s` (GKE · EKS · AKS), `managed` (Cloud SQL/PubSub · RDS/SQS · Azure SQL/Service Bus).

| Seam | Change |
|---|---|
| **Node model** | Add `CLOUD_SERVICE = "cloud-service"` + `CLOUD_EDGE = "cloud-edge"` type constants (`common/models/graph.py`). |
| **Seed grammar** | `normalize_seed`: recognize `cloudsvc:<provider>/<env>/<platform>/<name>` (already prefixed → identity). Unconfirmed edge targets use `cloudext:<host>`. |
| **Fetchable** | `_fetchable`: add `cloudsvc` to the follow-able kinds when `scope.explore_cloud` (crawl stays provider-neutral — it does NOT import cloud config). |
| **Scope** | `Scope.explore_cloud: bool = False` + `Scope.cloud_max_services: int = 8`. The gather layer sets `explore_cloud=cloud_configured()` at Scope construction — **no separate on/off flag**. |
| **Port** | `common/cloud/provider.py::CloudProvider` (Protocol) + `ServiceRef` / `LogEntry` + neutral `SERVERLESS`/`K8S`/`MANAGED`. Methods: `is_configured()`, `env_keys()`, `discover(env_key)`, `read_logs(ref, days, *, cap, min_severity)` (sync). |
| **Adapter + registry** | `common/cloud/gcp.py::GcpCloudProvider` (CAI + Cloud Logging + per-platform fallback, owns `KGA_GCP_ENV_MATRIX` / `_FILE`, lazy google-cloud imports). `common/cloud/factory.py::cloud_providers()` selects adapters via `KGA_CLOUD_PROVIDERS` (default `gcp`); a new cloud registers in one line. |
| **Discover producer** | `gather/explore/seeds/cloud_discover.py::cloud_service_seeds(...)` — iterates providers × envs, merges `ServiceRef`s, ranks → seeds + md. Called in `expansion_round` guarded by `scope.explore_cloud`. |
| **Fetcher** | `gather/crawl/fetch/cloud_service.py::CloudServiceFetcher(kind="cloudsvc")` — dispatches to the adapter by the id's `<provider>` segment; Tier 6 window + Tier 7 edges; imported in `fetch/__init__.py`. |
| **Sub-agent** | `gather/explore/planners/cloud_explore.py::build_cloud_explore_agent()` — `LlmAgent(output_schema=CloudExplorePlan)`, third `sub_agent` in `build_gather_agent` + run in `GatherAgent._plan`. |
| **Neutral flags** | `common/cloud/config.py`: `cloud_configured()` (enablement = a provider has a non-empty env map), `cloud_max_services()` (`KGA_CLOUD_MAX_SERVICES`), `cloud_windows()` (`KGA_CLOUD_WINDOWS`). |
| **Deps** | The `gcp` adapter extra: `google-cloud-asset/logging/run/container` (+ optional `-trace`). **Lazy-imported** (like `aiplatform`) so offline tests never touch them. Azure/AWS = future extras. |
| **Terraform** | Grant the agent SA `roles/cloudasset.viewer`, `roles/logging.viewer`, `roles/run.viewer`, `roles/container.viewer`, `roles/monitoring.viewer`, `roles/cloudtrace.user`; set `KGA_GCP_ENV_MATRIX` (or `_FILE`) — configuring it is what enables the tiers. |

**Not built (ponytail — say so up front):**
- No new crawl, no new traversal, no per-service LLM call. Tiers 6/7 ride the frontier; the sub-agent is one call.
- No mutation client, no kubectl/gcloud shell-out from the agent — read-only client libraries only.
- Console-URL → `gcpsvc:` classification is optional; the discover tier produces ids directly.
- No metrics/Monitoring tier yet (Tier 8 candidate). Logs + trace cover "how they communicate"; add
  Cloud Monitoring (latency/error-rate SLO signals) only when a ticket needs perf grounding.

---

## 8. Cross-cutting constraints (from this system's own history)

| Constraint | Why (memory / code) | How this plan honours it |
|---|---|---|
| **Opt-in, default off** | External reach that costs money + needs creds is gated (`follow_web`). | **Presence of cloud env config = opt-in**: `cloud_configured()` (a provider has a non-empty env map from `KGA_GCP_ENV_MATRIX`/`_FILE`) drives `Scope.explore_cloud`. No env map → off; a gather without it behaves exactly as today. There is no separate on/off flag. |
| **No blocking calls on the loop** | Serial blocking Vertex calls killed Cloud Run liveness (ERROR_TIMEOUT). | Every GCP call in `asyncio.to_thread`; windows expand under the crawl's existing semaphore; hard `max_seconds`. |
| **Grounding gate** | External LLM is a lead generator, never truth (Tier-3b). Confluence "leads" were cross-project noise. | The sub-agent ranks/labels; discovery + edges come only from GCP fields. No field → no node/edge. |
| **Provenance on every node** | The pack is the test basis; an ungrounded fact becomes a wrong test. | Each `gcpsvc:` Note carries its full resource path + the exact log filter; each edge carries its `origin` field. |
| **Redact everything sensitive** | Logs carry secrets/PII; the web fetcher already has an SSRF guard as a trust-boundary control. | Distiller keeps signatures+counts, strips secret/PII/connection-string patterns before persist. |
| **No silent caps** | Truncation reads as "covered everything" when it didn't. | max-services, 28-day window ceiling, dropped edges — all logged and surfaced in the gather reply. |
| **Least privilege** | — | SA gets only `*.viewer` roles; no write scope exists on any client. |
| **Config-driven env matrix** | `deployments/` tf is at repo root; slugs/names bit us before (wrong-slug 404s). | Env → (project, region, namespace) is one config map; wrong env is a config edit, not a code change. |

---

## 9. Phased roadmap (X0–X6)

Mirrors the loop's G0–G5 phasing; each phase is independently shippable and testable offline.

| Phase | Deliverable | Test (offline) |
|---|---|---|
| **X0** | `gcpsvc:` node kind + `normalize_seed`/`_fetchable`/`Scope.explore_gcp` plumbing (no reach yet). | Seed normalization + fetchable unit tests. |
| **X1** | GCP client factory + env matrix + `google-cloud-*` deps (lazy). Degrades to `None` unconfigured. | Factory returns `None` w/o creds; env-matrix JSON override parses. |
| **X2 — Tier 5** | `gcp_service_seeds` discovery + ranking; wired into `expansion_round` behind the flag. | Fake CAI client → asserts ranked `gcpsvc:` ids, cap respected, per-platform failure isolated. |
| **X3 — Tier 6** | `GcpServiceFetcher` with the expanding window + distill + **redaction**. | Fake Logging client with canned entries → asserts window widens 7→28 until "enough", redaction strips a planted secret, cap+shortfall logged. |
| **X4 — Tier 7** | Edge extraction (log/config/trace) → `LinkRecord`s; crawl walks the service graph. | Fake logs with an outbound host → asserts a grounded `gcp-edge` to the target `gcpsvc:` node; unconfirmed edge demoted. |
| **X5 — sub-agent** | `build_gcp_explore_agent` LlmAgent (re-rank/cluster/label) + `_plan` wiring; heuristic fallback w/o Vertex. | Fake BaseLlm (canned JSON → `output_schema`) — the offline planner-fake pattern already in `conftest`. |
| **X6 — deploy (IaC done ✓)** | `deployments/test-agent-v2/`: read-only viewer roles (`main.tf` `google_project_iam_member.cloud_viewer` over `var.cloud_exploration_projects` × the 6 viewer roles), `KGA_GCP_ENV_MATRIX` env var (`services.tf`, KGA only, set iff `var.gcp_env_matrix != ""`), the `[gcp]` extra baked into the image (`Dockerfile` → `.[bridge,gcp]`), + `terraform.tfvars.example` / `gcp-env-matrix.example.json`. `terraform validate` = clean. **Not yet applied** — live-verify on `klara-nonprod` + lesson capture still pending. | `terraform validate` clean; live gather on a real ticket → service subgraph in the pack; PQS unchanged or better. |

**X6 wiring (what shipped).** Config-presence is the sole toggle end-to-end: source ships an empty matrix,
and `gcp_env_matrix=""` (default) means the `KGA_GCP_ENV_MATRIX` env var is omitted → the adapter is
unconfigured → tiers 5/6/7 no-op. To enable: set `gcp_env_matrix` (inline the JSON from
`gcp-env-matrix.example.json`) **and** list `cloud_exploration_projects` (grants the viewer roles). To apply:
`terraform apply` then rebuild the image (the `[gcp]` extra must be in the running image) — follow the repo's
existing repo-target-apply → build → full-apply order. **Caveat:** the read APIs (`cloudasset`, `logging`,
`monitoring`, `cloudtrace`, `container`) must be enabled on each *target* project being read; they are not
force-enabled here (a target project may be cross-project, e.g. `klara-prod`, which this stack doesn't own).

**Convergence / de-risk.** X2–X4 are usable without the LLM (numeric rank + deterministic edges); X5 only
sharpens them. If Agent Engine / cost proves the flag too heavy, it stays off with zero blast radius.

---

## 10. Open questions

1. **Scope of the CAI search** — org, folder, or an explicit project list? Least-privilege favours a
   configured folder/project list over org-wide `searchAllResources`.
2. **prod log access** — reading `klara-prod` logs from a nonprod-deployed agent needs a cross-project
   viewer binding; confirm the security posture before enabling `prod` in the matrix (default the matrix to
   nonprod envs only until approved).
3. **Trace availability** — if Cloud Trace isn't populated for these services, Tier 7 leans on log+config
   edges only; trace is the best signal but optional.
4. **Managed-service allow-list** — which managed types are in scope (SQL, Pub/Sub, Redis, Tasks…)?
   Config-driven; start with Cloud SQL + Pub/Sub (the task-store + eventing the agents already use).
