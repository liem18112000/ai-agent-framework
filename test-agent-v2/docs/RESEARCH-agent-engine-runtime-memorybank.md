# Research — deploying the agent to Vertex AI Agent Engine (Agent Runtime) + using its Memory Bank

**Question:** how do I deploy this agent to the Agent Runtime
(`console.cloud.google.com/agent-platform/runtimes`) and use **the Memory Bank that comes with the
Agent Runtime**?

**Status: research / options only.** No code changed by this doc. Grounded in the installed SDK
(`google-adk 2.8.0`, `vertexai.agent_engines`, `google.adk.memory.VertexAiMemoryBankService`), this
repo's code, and the current Google docs (sources at the end). Load-bearing claims are corroborated
across ≥2 sources; a few items are marked **[verify]** where the public docs render as JS shells.

---

## 0. TL;DR / the one thing to understand first

"Agent Runtime" = **Vertex AI Agent Engine** (formerly Reasoning Engine). Its **Memory Bank** is a
**managed conversational long-term memory** — Gemini extracts *facts/preferences* from an Agent
Engine **Session** and stores them **scoped to a `user_id`**, retrievable by similarity search.

**It is NOT the same thing as this repo's `common/memory`.** Our bank is a *domain knowledge base*
(the crawled Jira/Confluence link-graph + distilled notes + self-learning lessons, GCS source-of-truth
+ pgvector recall). Memory Bank is *per-user chat memory* ("the user prefers API-level tests"). So:

- **Deploying to Agent Engine ≠ replacing `common/memory`.** Keep our bank for the domain KG; add
  Memory Bank only for cross-session *user/conversation* recall. They complement, they don't substitute.
- **Agent Engine ≠ our MCP gateway.** Agent Engine hosts **one `root_agent`** behind its own
  `query()`/`stream_query()` + REST API and its own managed **Sessions**; it does **not** speak our
  A2A/`to_a2a` surface or the single MCP gateway. Deploying to it is a *parallel/alternative* serving
  surface, and it **reverses decision made in commit `3787360`** ("drop the Agent Engine path" in
  favour of Cloud Run + gateway + native MCP for local Claude). Decide that trade first (§5).

The good news: the "use the runtime's Memory Bank" part is nearly free — **an ADK agent deployed to
Agent Engine Runtime uses `VertexAiMemoryBankService` by default** (the runtime provisions Sessions +
a Memory Bank for the engine).

---

## 1. What Agent Engine + Memory Bank are (grounded)

- **Agent Engine / Agent Runtime**: a managed runtime that hosts an ADK agent, gives it managed
  **Sessions** (`VertexAiSessionService`), tracing, autoscaling, and a **Memory Bank**. A deployed
  engine is a resource: `projects/<n>/locations/<loc>/reasoningEngines/<ID>` — that trailing `<ID>` is
  the **`agent_engine_id`**.
- **Memory Bank** (managed, in Agent Engine):
  - **Generate**: "Using **Gemini** models, Memory Bank can analyze a user's conversation history …
    (stored in Agent Engine Sessions) to extract key facts, preferences, and context." Runs
    **asynchronously**; consolidates + resolves contradictions with existing memories.
  - **Retrieve**: all-facts, or **similarity search (embeddings)** for topic-relevant memories.
  - **Scope**: "organized by your defined **scope, such as user ID**."
  - **Generation model is Gemini, managed** — independent of our agent's model (we run Claude via
    LiteLlm; that's fine — Memory Bank's LLM is a separate, Google-managed one).
  - TTL on memories is supported per the ADK/overview docs **[verify — single source]**.

### ADK API (confirmed by SDK introspection + adk.dev)
`google.adk.memory.VertexAiMemoryBankService(project=…, location=…, agent_engine_id=…)` with methods:
`add_session_to_memory(session)` (→ GenerateMemories), `add_events_to_memory`, `add_memory(...)`
(direct ingest), `search_memory(app_name, user_id, query)` (→ RetrieveMemories), `retrieve_profiles`.
Wired onto the `Runner(memory_service=…)`. Agents read it via the built-in tools
`load_memory`/`LoadMemoryTool` (agent decides when) or `preload_memory`/`PreloadMemoryTool`
(auto-fetch at turn start).

---

## 2. How to deploy this agent to Agent Engine

Agent Engine builds a **fresh container from your source** — so you ship the packages + pin the deps
(our Cloud Run image is not reused). Two ways:

### A) CLI (fastest)
```bash
adk deploy agent_engine \
  --project=klara-nonprod --region=<AE_REGION> \
  --display_name="knowledge-gathering" \
  --staging_bucket="gs://klara-nonprod-kga-v2-memory" \
  src/knowledge_gathering            # dir exposing root_agent
# → Resource name: projects/…/locations/…/reasoningEngines/<AGENT_ENGINE_ID>
```

### B) Python SDK (what the dropped `deployment/deploy.py` did — recover it from git `3787360^`)
```python
import vertexai
from vertexai import agent_engines
from vertexai.preview.reasoning_engines import AdkApp
from knowledge_gathering.agent import root_agent   # our custom BaseAgent router

vertexai.init(project="klara-nonprod", location="<AE_REGION>",
              staging_bucket="gs://klara-nonprod-kga-v2-memory")
remote = agent_engines.create(
    AdkApp(agent=root_agent, enable_tracing=True),
    display_name=root_agent.name,
    requirements=[                       # Agent Engine builds a NEW container — pin our runtime deps
        "google-cloud-aiplatform[adk,agent_engines]>=1.93",
        "google-adk>=2.8", "litellm", "anthropic[vertex]",
        "httpx", "python-dotenv", "pydantic",   # + whatever common/* imports at runtime
    ],
    extra_packages=["src/common", "src/knowledge_gathering"],   # ship our source
    env_vars={k: os.environ[k] for k in (
        "VERTEX_PROJECT","VERTEX_LOCATION","VERTEX_MODEL","GCS_BUCKET",
        "ATLASSIAN_BASE_URL","ATLASSIAN_EMAIL","ATLASSIAN_API_TOKEN")}
              | {"GOOGLE_GENAI_USE_VERTEXAI": "1"},
)
print(remote.resource_name)   # projects/…/reasoningEngines/<AGENT_ENGINE_ID>
```

Notes specific to us:
- **One engine per `root_agent`.** We have three (`knowledge_gathering`, `test_plan_definition`,
  `test_evaluation`) + `testing_agent`. Agent Engine hosts one root each → up to 4 engines, OR deploy
  only the autonomous `testing_agent` (it already chains gather→…→implement) as a single engine.
- **Secrets**: `env_vars` are stored on the engine; prefer Secret Manager refs for
  `ATLASSIAN_API_TOKEN` etc. rather than plaintext env **[verify: Agent Engine secret-env support]**.
- **Model**: our Claude-via-LiteLlm runs as *our code* inside the container, so it should work on
  Agent Engine (it's just Python calling Vertex Anthropic) — **[verify: no doc explicitly blesses
  non-Gemini on Agent Engine; high confidence because the runtime executes your `AdkApp`]**. Memory
  Bank's own generation stays Gemini regardless.
- **Region**: our stack is `europe-west6` (Cloud SQL) / `global` (Vertex Claude). **Agent Engine +
  Memory Bank region availability must be checked** — pick an AE-supported region; it need not equal
  the Cloud SQL region. **[verify]**

---

## 3. How to use the runtime's Memory Bank

Once an engine exists you have its `agent_engine_id`. Two integration levels:

### 3a. Automatic (deployed on Agent Engine)
Per the official overview: *"If you're using the Agent Engine ADK template, the agent uses the
`VertexAiMemoryBankService` by default when deployed to Agent Engine Runtime."* So a deployed ADK
agent gets managed Sessions + Memory Bank wired for free — memories generate from each session and are
retrievable per `user_id`.

### 3b. Explicit wiring (local Runner, or to be deliberate)
```python
from google.adk.memory import VertexAiMemoryBankService
from google.adk.sessions import VertexAiSessionService     # managed sessions feed the bank

mem = VertexAiMemoryBankService(project="klara-nonprod", location="<AE_REGION>",
                                agent_engine_id="<AGENT_ENGINE_ID>")
runner = Runner(app_name=root.name, agent=root,
                session_service=VertexAiSessionService(...), memory_service=mem)

await mem.add_session_to_memory(session)                    # Gemini extracts memories (async)
hits = await mem.search_memory(app_name=root.name, user_id=uid, query=text)   # similarity, scoped
```
To let the agent *read* memory, add a tool to an **LlmAgent**: `tools=[load_memory]` (or
`preload_memory` to auto-inject at turn start).

### The integration nuance for THIS repo
Our routers/orchestrators are **deterministic custom `BaseAgent`s (D1)** — they don't take `tools=`,
so the `load_memory`/`preload_memory` *tool* path doesn't attach to them directly. Options:
1. **Imperative** — call `mem.search_memory(...)` inside a `BaseAgent` and fold results into the pack
   (mirrors how we already inject grounded lessons); cleanest fit for our deterministic design.
2. **Give the new D15/D16 `LlmAgent`s the `load_memory` tool** — but note `output_schema` planners
   **cannot** also take `tools=` (ADK constraint we recorded in D15/§5.1), so memory-tool use needs a
   *non-output_schema* LlmAgent (e.g. a future refine/define reasoner), not the enumerators.
3. **Let the runtime default do it** (§3a) and only *read* via `search_memory` where useful.

`build_runner` (`common/adk/services.py`) currently sets **no `memory_service`** — adding one
(guarded on an `AGENT_ENGINE_ID` env, falling back to `InMemoryMemoryService`/none locally) is the
minimal code change.

---

## 4. Memory Bank vs our `common/memory` — how they coexist

| | `common/memory` (ours) | Agent Engine Memory Bank |
|---|---|---|
| Content | Crawled Jira/Confluence graph + distilled notes + self-learning **lessons** | Per-user **conversation** facts/preferences (Gemini-extracted) |
| Scope | Global knowledge base (per pack/`context_id`) | Per **`user_id`** |
| Store | GCS (truth) + pgvector recall (hybrid) | Managed (opaque) |
| Retrieval | `search_nodes` / `recall_lessons` (hybrid vector∪tsvector∪SQL) | similarity search (embeddings) |
| Who writes | our crawler/refine/learn pipeline | Gemini, async, from sessions |

They answer different questions. **Recommendation:** keep `common/memory` as the domain KG; adopt
Memory Bank (if at all) for *"what did this user/tester establish across past runs"* — e.g. remember a
tester's methodology preferences or previously-approved scoping across tickets. Do **not** migrate the
crawled KG or the B0–B6 lesson machinery into Memory Bank (different abstraction, and D7 keeps
interrogation state in the bank).

---

## 5. The architectural decision (do this before any code)

Deploying to Agent Engine is a **serving-surface choice**, and it conflicts with the current design:

- **Today:** Cloud Run — 3 A2A agents (`main:app`=`to_a2a`) + 1 MCP gateway; **local Claude connects to
  the single MCP `testing-agent` endpoint**; sessions on Cloud SQL (`DatabaseSessionService`); memory =
  `common/memory`. This is what commit `3787360` deliberately chose over Agent Engine.
- **Agent Engine:** managed Sessions + Memory Bank + tracing + autoscaling, but you query it via the
  **Agent Engine API** (`.query`/`.stream_query`/REST), **not** our MCP gateway or A2A. Local Claude
  would talk to it via a *different* connector (an Agent Engine client), not `install-mcp`.

**When Agent Engine wins:** you want managed session/memory/observability and are happy to use its
query API. **When the current gateway wins:** you want the one deterministic MCP endpoint for local
Claude + our own memory/observability. **Hybrid** is possible (keep the gateway for local Claude; run
an Agent Engine instance *only* to own the Memory Bank, which our Cloud Run agents call via
`VertexAiMemoryBankService(agent_engine_id=…)` over the API) — this gets you the Memory Bank **without**
moving the serving surface. That hybrid is likely the lowest-risk way to satisfy the literal ask.

---

## 6. Recommended path (lowest-risk first)

1. **Spike (no commit):** create ONE Agent Engine instance (CLI, throwaway) → capture its
   `agent_engine_id`. Confirm region availability + that our Claude/LiteLlm agent boots there.
2. **Hybrid Memory Bank:** from the *existing Cloud Run* agents, add an opt-in `memory_service =
   VertexAiMemoryBankService(agent_engine_id=…)` in `build_runner` (guarded by an `AGENT_ENGINE_ID`
   env; `None` locally/offline). Read via imperative `search_memory` in a `BaseAgent`; write via
   `add_session_to_memory` in a drain plugin. Keep `common/memory` unchanged. → gets the runtime's
   Memory Bank without abandoning the gateway.
3. **Only if you want the managed runtime too:** restore `deployment/deploy.py` from git `3787360^`,
   modernize the deps, and deploy the `testing_agent` root as an engine; decide gateway-vs-AE per §5.

### Verification gates / open items
- **[verify]** Agent Engine + Memory Bank **region** for `klara-nonprod` (pick an AE-supported region).
- **[verify]** non-Gemini (Claude/LiteLlm) agent runs on Agent Engine end-to-end (high confidence).
- **[verify]** Secret Manager env refs on Agent Engine (vs plaintext `env_vars`).
- **[verify]** exact `create(...)` memory/generation config knobs (similarity-search config, TTL,
  scope key) — docs render as JS shells; confirm from the GitHub sample notebooks (source below).
- Cost/quota: Memory Bank generation + retrieval + Agent Engine runtime are billed separately from
  Cloud Run; check the pricing page before enabling broadly.

---

## Sources
- [ADK — Memory (adk.dev)](https://adk.dev/sessions/memory/) — `BaseMemoryService`,
  `VertexAiMemoryBankService(project, location, agent_engine_id)`, `Runner(memory_service=…)`,
  `load_memory`/`preload_memory`.
- [Vertex AI Agent Engine Memory Bank — overview](https://cloud.google.com/agent-builder/agent-engine/memory-bank/overview)
  — methods; "uses `VertexAiMemoryBankService` by default when deployed to Agent Engine Runtime";
  similarity search scoped to identity; TTL.
- [Vertex AI Memory Bank in public preview — Google Cloud blog](https://cloud.google.com/blog/products/ai-machine-learning/vertex-ai-memory-bank-in-public-preview)
  — Gemini-extracted memories from Agent Engine Sessions, consolidation, scope = user ID, framework
  support.
- [ADK — deploy to Agent Runtime/Engine](https://adk.dev/deploy/agent-runtime/) — `adk deploy
  agent_engine`, `reasoningEngines/<ID>` resource name.
- [Set up Memory Bank](https://cloud.google.com/agent-builder/agent-engine/memory-bank/set-up) ·
  [ADK quickstart](https://cloud.google.com/agent-builder/agent-engine/memory-bank/quickstart-adk) ·
  [GCP sample notebooks](https://github.com/GoogleCloudPlatform/generative-ai/tree/main/gemini/agent-engine/memory).
- Local: installed `google-adk 2.8.0` (`VertexAiMemoryBankService` + `vertexai.agent_engines.AdkApp/create`);
  the dropped `deployment/deploy.py` at git `3787360^`.
