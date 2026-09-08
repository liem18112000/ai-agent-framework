# Enhancement — the ADK-native cutover (drop the a2a-sdk shells, Gemini, and the dual model plumbing)

The **executable plan** for the "next enhancement": finish the migration by making `test-agent-v2`
**ADK-native end to end** — remove every module that only exists to serve the old a2a-sdk shell,
remove the **Gemini** backend, and re-express model access as a small **`ModelProvider` interface**
(Claude-on-Vertex the sole impl today, pluggable for future models). Nothing here touches
`test-agent-v1`.

> **Status: design/plan only.** This document is the deliverable. No code is changed by it. Each
> milestone below (C0–C6) is the unit of work when execution is authorized.

Cross-refs: invariants **I1–I8** (§1 of [`IMPLEMENTATION-PLAN.md`](IMPLEMENTATION-PLAN.md), I8 added
here), decisions **D1–D9** ([`DECISIONS.md`](DECISIONS.md), extended with **D10–D13** here), sample
idioms **E1–E8** ([`ENHANCEMENT-adk-idioms.md`](ENHANCEMENT-adk-idioms.md)).

---

## 0. Objective & the three locked decisions

Ship KGA + TPD + the evaluator running **only** on the ADK-native surface, reachable by **local
Claude** through **one MCP gateway**, with the model reached through an extensible interface — and
delete everything the a2a-sdk shell required that the ADK-native path does not.

Three decisions were confirmed with the user before writing this plan; they set the target shape:

| # | Question | Decision |
|---|----------|----------|
| 1 | What is "local Claude" for the model layer? | **Keep Claude-on-Vertex, just abstract it.** `VertexClaudeProvider` is the only concrete provider today; the point is the **interface** so a future `LocalClaudeProvider` (e.g. `ANTHROPIC_BASE_URL` → a local endpoint) drops in without touching agents. **Gemini removed.** |
| 2 | Which serving surface survives? | **Collapse to ADK-native + gateway.** `main.py` (`get_fast_api_app`, `a2a=True`) is the one server; the **MCP gateway** (`src/gateway`) is local Claude's single entry. **Drop** per-agent `adk_app.py` (`to_a2a`), `server.py` (a2a-sdk shell), `a2a_card.py`, and the standalone per-agent bridge launchers. |
| 3 | Deliverable now? | **Implementation-plan docs only.** This file (+ the D10–D13 delta in `DECISIONS.md` and the index line in `docs/README.md`). |

Target runtime after the cutover:

```
local Claude ──MCP──▶ gateway (python -m gateway, ONE MCP server)
                         │  composes each agent's bridge.mcp_server.register_tools  (I4: same tools)
                         └──A2A──▶ main:app  (get_fast_api_app, a2a=True, one FastAPI app)
                                     ├─ knowledge_gathering.agent:root_agent
                                     ├─ test_plan_definition.agent:root_agent
                                     └─ test_evaluation.agent:root_agent
                                   model calls ──▶ common/adk/providers → VertexClaudeProvider
                                   sessions ──▶ DatabaseSessionService (SESSION_SERVICE_URI)
```

---

## 1. Current state (grounded inventory)

The ADK rebuild (M0 → A0 → A.0 → A1 → A2 → B) is **done offline**. What remains is that the **v1
a2a-sdk shells still live beside the ADK code and are still partly load-bearing**, and the model
layer still carries a **Gemini branch** plus a **second, separate model plumbing** for the engine.

> **Already landed in the G-milestones (since this was drafted):** the single MCP gateway
> (`src/gateway`) is built, the three agents are **A2A-only** (single container each), and the
> **standalone per-agent bridge launchers** (`<agent>/bridge/__main__.py`) + each `bridge/mcp_server.py`'s
> standalone `mcp`/`http_app`/`agent_card`/`send_raw`/`test` were **deleted** — every `mcp_server.py` is
> now *just* `register_tools`. So in the delete-lists below those launchers are already gone; the
> remaining cutover delta is the **model layer (C1)**, the **executor extraction (C2)**, the a2a-sdk
> shells incl. per-agent `adk_app.py`/`serve.py`/`server.py`/`a2a_card.py` (**C3**), and the **`main:app`
> collapse (C4)**. See [`DESIGN-mcp-gateway.md`](DESIGN-mcp-gateway.md).

### 1a. Two model plumbings (both Claude-on-Vertex today)

| Seam | File | What it does | Gemini? |
|------|------|--------------|---------|
| **ADK `LlmAgent` model** | `common/adk/model.py` (`agent_model`, `claude_llm`) + `common/adk/config.py` (`model_backend`, `gemini_model`) | Returns a `LiteLlm("vertex_ai/claude-sonnet-5")` **or a Gemini model-id string** | **Yes — the branch to delete** |
| **Engine text calls** | `common/llm/vertex.py` (`vertex_config`, `complete`, `agenerate`) | The **live** LLM path: questions / understanding / distill call this directly (`AnthropicVertex`) | No |

Key fact established while scoping: **`agent_model()`/`claude_llm()` are currently only *re-exported*
from `common/adk/__init__.py` and referenced by tests** — no live `LlmAgent` consumes them yet (per
**D4**, the engine still owns its own Vertex calls). So removing the Gemini branch is **low-risk**:
it deletes an unused code path.

### 1b. The a2a-sdk shells still present (and their live couplings)

`grep 'from a2a'` in `src/` returns 17 files. They fall into two groups:

**Group A — pure a2a-sdk shells, no ADK-native need → DELETE:**
- `common/card.py`, `common/taskstore.py`, `common/ops.py`, `common/executor.py`, `common/middlewares/*`
- `common/adk/serve.py` (the `to_a2a` custom serve; imports `ops` + `middlewares`)
- per agent: `<agent>/server.py`, `<agent>/a2a_card.py`, `<agent>/adk_app.py`
- per agent: `<agent>/executor/base.py` (`*Executor` classes) + `<agent>/executor/common.py` (`reply`/`now` a2a seam)

**Group B — domain logic that *lives inside* the executor packages and is reused by the ADK agents
→ EXTRACT FIRST, then the shell above can go:**

| Reused by | Imports from the executor shell |
|-----------|--------------------------------|
| `knowledge_gathering/agents/gather_agent.py` | `executor.common.build_client`, `executor.gather.{run_gather, summarize…}` |
| `knowledge_gathering/agent.py` (root) | `executor.refine.wants_refine` |
| `test_plan_definition/agents/define_agent.py` | `executor.define.summarize_define` |
| `test_plan_definition/agents/implement_agent.py` | `executor.implement.{_capture_implement, summarize_implement}` |
| `test_plan_definition/agent.py` (root) | `executor.define.wants_define` |
| `test_evaluation/agent.py` (root) + `eval/adk_metrics.py` | `executor.base.{golden_for, golden_plan_for}` |
| `common/llm/pg/backfill.py`, `loop/fetch/codegraph.py` | `common.executor.build_bank` (already lifted to `common/memory/factory.py`; these still import the old path) |

**Keep regardless:** the whole framework-neutral engine (`common/{memory,learn,interrogate,llm,
atlassian,codegraph,extract,models,db.py,monitoring.py}`, each agent's `loop/explore/define/implement/
llm/render/memory/models/pack.py`), **`common/bridge/`** (the gateway uses it), each agent's
**`bridge/mcp_server.py:register_tools`** (the gateway composes them — this **is** the MCP surface, I4),
`main.py`, `src/gateway/`, `src/testing_agent/` (the E7 `SequentialAgent`).

---

## 2. Part 1 — the model interface layer (and Gemini removal)

### 2.1 Target abstraction

A tiny provider interface under `common/adk/providers/`, the **one documented extension point** for
"which model, reached how". Acyclic: `common/adk/*` may import `common/llm/*`, never the reverse.

```python
# common/adk/providers/base.py                                   [new]
from typing import Protocol

class ModelProvider(Protocol):
    name: str
    def is_configured(self) -> bool: ...                 # replaces the raw vertex_config() gate (I7)
    def llm_agent_model(self, *, max_tokens: int | None = None): ...  # ADK LlmAgent model (LiteLlm) or None
    # engine text calls (optional to route now — see 2.3 Option A vs B):
    def complete(self, prompt: str, *, max_tokens: int) -> str: ...
    async def agenerate(self, prompt: str, *, max_tokens: int) -> str: ...
```

```python
# common/adk/providers/vertex_claude.py                          [new]
class VertexClaudeProvider:
    name = "claude"                                      # (== Claude-on-Vertex)
    def is_configured(self) -> bool:
        return vertex_config() is not None               # from common.llm.vertex
    def llm_agent_model(self, *, max_tokens=None):
        # the old claude_llm() body, verbatim: LiteLlm("vertex_ai/<model>", thinking=disabled,
        # max_tokens=…, vertex_project/location) — the I5 gotchas stay here, one place.
        ...
    def complete(self, prompt, *, max_tokens):           # delegates to common.llm.vertex.complete
        ...
    async def agenerate(self, prompt, *, max_tokens):    # delegates to common.llm.vertex.agenerate
        ...
```

```python
# common/adk/providers/__init__.py                               [new]
_REGISTRY = {"claude": VertexClaudeProvider}             # add "local"/"anthropic"/… here later — nothing else changes
def get_provider() -> ModelProvider:
    return _REGISTRY[get_config().model_backend]()       # default "claude"; unknown name → clear KeyError
```

### 2.2 Edits to the existing model files

- **`common/adk/config.py`** — **drop** `gemini_model`; change `model_backend: Literal["claude","gemini"]`
  → `model_backend: str = "claude"` (validated against the registry, open for future names).
- **`common/adk/model.py`** — `agent_model()` → `return get_provider().llm_agent_model(max_tokens=…)`;
  **delete** the `if cfg.model_backend == "gemini"` branch. Keep `claude_llm()` as a thin deprecated
  alias to `VertexClaudeProvider().llm_agent_model()` (or delete once tests are repointed).
- **`common/adk/__init__.py`** — export `get_provider` alongside/instead of `agent_model`/`claude_llm`.

### 2.3 The engine seam — Option A (recommended) vs B

The engine (`interrogate/questions.py`, `interrogate/understanding.py`, `llm/distill/factory.py`,
`llm/{questions,understanding}.py`, `llm/distill/claude.py`) calls `vertex_config()`/`complete()`
**directly**. Two ways to relate that to the new interface:

- **Option A (recommended — minimal, honours D6 "reuse engine unchanged"):** leave the engine's
  direct `common/llm/vertex.py` calls as they are — they are *already* Claude-on-Vertex, Gemini-free.
  Declare `common/llm/vertex.py` **"the `VertexClaudeProvider`'s transport"** in a module docstring,
  and make the `ModelProvider` interface authoritative for **ADK `LlmAgent` model selection** + the
  documented extension recipe. A future provider swaps the transport behind the same
  `is_configured()` env signal. **No engine files edited.**
- **Option B (fuller unification, later):** route the engine's `complete`/`agenerate` through
  `get_provider()` too (≈6 engine modules change their import from `common.llm.vertex` to
  `common.adk.providers`). Cleaner "one seam", but edits the reused engine and risks a
  `common/llm → common/adk` import cycle — do it only after the engine is promoted to its own package.

**This plan adopts Option A.** The interface is real at the ADK layer and is the single place new
models are registered; the engine keeps its tested path. Option B is a tracked follow-up.

### 2.4 Gemini scrubbing (whole tree)

Delete every Gemini reference so `grep -ri gemini src/` returns nothing:
- `common/adk/config.py` — the field + Literal (2.2).
- `common/adk/model.py` — the branch (2.2).
- `knowledge_gathering/explore/ask_llm.py` — the "Gemini is a TODO" comment (§17-18): reword to
  "a different provider via `ModelProvider` is a TODO".
- `test_evaluation/eval/config.py` — the "Claude-via-LiteLlm or Gemini" judge comment: drop "or Gemini".
- `.env.example` — remove `TESTAGENT_GEMINI_MODEL` and `GOOGLE_GENAI_USE_VERTEXAI` (the Gemini/`adk web`
  native-genai switch); keep `VERTEX_*` (the Claude path).

### 2.5 Part-1 gates

- **I5** — a live "thinking disabled + full-length JSON parses" test now runs through
  `VertexClaudeProvider.llm_agent_model()` (was `claude_llm()`); same assertion.
- **I7** — a "provider unconfigured → engine takes the heuristic path" test: `get_provider().is_configured()`
  is `False` when `VERTEX_*` unset ⇒ deterministic output (unchanged behaviour, new gate point).
- **I8 (new)** — model access is *only* through `ModelProvider`/`common.llm.vertex`; a grep gate that
  `google.adk.models` and `LiteLlm(...)` appear **only** inside `common/adk/providers/`.
- `grep -ri gemini src/` empty; `tests/test_adk_config.py` updated (no `gemini` case, add a
  provider-registry case).

---

## 3. Part 2 — un-couple the domain logic from the executor shells

Before any a2a shell is deleted, the Group-B domain functions (§1b) move into framework-neutral
modules, and their importers are repointed. This is the load-bearing step; do it as its own milestone
(**C2**) with the ADK-router tests as the gate.

| Move | From (deleted after) | To (new/neutral) |
|------|----------------------|------------------|
| `run_gather`, gather summaries | `knowledge_gathering/executor/gather.py` | `knowledge_gathering/gather.py` [new] |
| `wants_refine`, refine summaries | `knowledge_gathering/executor/refine.py` | `knowledge_gathering/refine.py` [new] |
| memory read helpers | `knowledge_gathering/executor/memory.py` | fold into `knowledge_gathering/reads.py` [new] |
| `build_client` | `knowledge_gathering/executor/common.py` | `knowledge_gathering/atlassian_client.py` [new] |
| `wants_define`, `summarize_define`, `extract_ctx` | `test_plan_definition/executor/define.py` | `test_plan_definition/define_ops.py` [new] |
| `run_implement`, `summarize_implement`, `_capture_implement` | `test_plan_definition/executor/implement.py` | `test_plan_definition/implement_ops.py` [new] |
| `golden_for`, `golden_plan_for` | `test_evaluation/executor/base.py` | `test_evaluation/golden.py` (exists) |
| `now()` (plain `datetime`) | `common/executor.py` | `common/adk/util.py` [new] (or inline) |
| `build_bank` importers | `common/executor` path in `codegraph.py`, `pg/backfill.py` | repoint to `common/memory/factory.py` (already the real home) |

**Dropped, not moved:** `reply()` (a2a `TaskUpdater`/`EventQueue` — no ADK meaning; the ADK agents
already `yield Event(...)`), and the `*Executor` classes in each `executor/base.py`.

Repoint importers: `agents/gather_agent.py`, `agents/define_agent.py`, `agents/implement_agent.py`,
each root `agent.py`, and `eval/adk_metrics.py` switch their imports from `…executor.*` to the new
neutral modules. **Gate:** `tests/test_adk_kga.py`, `test_adk_tpd.py`, `test_adk_eval.py`,
`test_adk_autonomous.py` stay green with **byte-identical** node/brief/scenario output (the existing
equivalence assertions); no `import …executor` remains except in the files queued for deletion in C3.

---

## 4. Part 3 — delete the a2a-sdk shells & relocate what's transport-neutral

Once C2 lands, Group-A (§1b) deletes cleanly. Two pieces are **relocated, not deleted**, because they
are transport-neutral and still needed by the ADK-native app:

- **`BearerAuthMiddleware`** (`common/middlewares/auth.py`) → **`common/adk/auth.py`** [new]. It is a
  plain ASGI middleware; it wraps `main:app` (see C4). `get_fast_api_app` ships **no** auth of its own —
  deleting the middleware outright would leave the A2A endpoints open (**gap flagged**, see R-b).
- **health routes** — `get_fast_api_app` exposes ADK's own endpoints; if Cloud Run's existing
  `/livez`/`/readyz` probe paths must stay, add a 3-line route to `main.py` (or repoint the probes to
  ADK's health path). Verify which ADK 2.x serves before deleting `common/ops.py`. `[verify @2.x]`

**Delete list (C3):**
```
common/card.py  common/taskstore.py  common/ops.py  common/executor.py  common/middlewares/*
common/adk/serve.py
knowledge_gathering/{server.py, a2a_card.py, adk_app.py, executor/*}
test_plan_definition/{server.py, a2a_card.py, adk_app.py, executor/*}
test_evaluation/{server.py, a2a_card.py, adk_app.py, executor/*}
```
**Gates:** `grep -rl 'from a2a' src/` returns **only** files inside code that `get_fast_api_app(a2a=True)`
itself needs (ideally none in our packages); the **I6** no-cross-agent-import gate still passes; the
**DatabaseSessionService** (`SESSION_SERVICE_URI`) is confirmed to subsume the retired a2a
`DatabaseTaskStore` for task durability `[verify @2.x]`.

---

## 5. Part 4 — one entrypoint + one gateway

- **`main.py`** becomes THE app. Wrap the `get_fast_api_app(...)` result with `common/adk/auth.py`'s
  `BearerAuthMiddleware` (bearer for the A2A/REST surface). Keep the `SESSION_SERVICE_URI` /
  `ARTIFACT_SERVICE_URI` wiring it already has.
- **`Dockerfile`** — agent CMD `knowledge_gathering.adk_app:app` → **`main:app`**; the bridge CMD
  (`python -m knowledge_gathering.bridge`) → **`python -m gateway`** (the one MCP server).
- **`src/gateway/`** — unchanged in shape; it composes `register_tools` from each agent's
  `bridge/mcp_server.py` (kept). Confirm the gateway's `BridgeSession` calls the A2A message endpoint
  at the path `get_fast_api_app(a2a=True)` serves per agent. `[verify @2.x]`
- **`pyproject.toml`** — drop the three `*-bridge` scripts; add one `gateway = "gateway.__main__:main"`
  (or keep `python -m gateway`). Keep `a2a-sdk` (get_fast_api_app's `a2a=True` needs it) and the
  `[bridge]` extra (`mcp`, the gateway). Prune the `DatabaseTaskStore` note.
- **`.env.example`** — Gemini vars removed (§2.4); document `SESSION_SERVICE_URI`
  (`postgresql+asyncpg://…`), `ARTIFACT_SERVICE_URI` (`gs://…`), and the gateway envs
  (`KGA_A2A_URL`/`TPD_A2A_URL`/`TEV_A2A_URL`, `A2A_BEARER_TOKEN`, `GATEWAY_BEARER_TOKEN`).

**Gates:** `uvicorn main:app` boots; `/list-apps` lists the 3 agents; `python -m gateway` lists the
**same MCP tool names** as before (I4 skill-parity → tool-parity test via `tests/test_gateway.py`);
bearer 401 without token on the A2A surface.

---

## 6. Milestones

Format: **Goal · Gate · DoD · Size.** Sequence is strict — each milestone's gate is the next one's
safety net.

> **Progress: C1 ✅ done (2026-09-08).** `common/adk/providers/{base,vertex_claude,__init__}.py` added;
> `config.py`/`model.py`/`__init__.py` route through `get_provider()`; Gemini scrubbed
> (`grep -ri gemini src/` empty); `.env.example` cleaned. Gates green: `test_adk_config` (provider
> registry + unknown-backend error), `test_model_access_gate` (I8 — `LiteLlm(`/`google.adk.models` only
> in `providers/`; Gemini-scrubbed), `test_adk_foundation` (I5/I7). Option A: the engine's
> `common/llm/vertex.py` path is untouched. **Next: C2.**

| # | Milestone | Gate | Size |
|---|-----------|------|------|
| **C0** | **Pre-flight/freeze** — confirm the full v2 suite is green as the baseline; log the `[verify @2.x]` unknowns (get_fast_api_app A2A card + message path, its auth story, task durability). | current suite green; unknowns listed in this doc §8 | S |
| **C1** | **Model interface + Gemini removal** (§2) — `common/adk/providers/*`, edit `model.py`/`config.py`/`__init__.py`, scrub Gemini, update `.env.example`. | I5/I7/I8 gates; `grep -ri gemini src/` empty; `test_adk_config` updated | M |
| **C2** | **Un-couple domain logic** (§3) — extract Group-B funcs to neutral modules; repoint agents + `adk_metrics`. | `test_adk_{kga,tpd,eval,autonomous}` green, byte-identical outputs; no live `import …executor` | L |
| **C3** | **Delete a2a shells** (§4) — relocate `BearerAuthMiddleware`→`common/adk/auth.py`; delete the Group-A list. | I6 import gate; `from a2a` gone from our packages; suite green minus dropped a2a tests | M |
| **C4** | **One entrypoint + gateway** (§5) — `main:app` (+auth), Dockerfile, pyproject, gateway front. | boot + `/list-apps` = 3; gateway tool-parity (I4); bearer enforced | M |
| **C5** | **Test reconciliation** (§7) — drop/rewrite the a2a-shell tests; keep equivalence + all invariant gates. | full suite green; MCP surface covered via `test_gateway` | M |
| **C6** | **Deploy** — `deployments/test-agent-v2` (repo root): container start cmd → `main:app`; one gateway service; `SESSION_SERVICE_URI` from the existing Cloud SQL; parity smoke through the gateway. | deployed parity smoke; v1 untouched | M |

```
C0 → C1 → C2 → C3 → C4 → C5 → C6
      (C1 independent of C2; C3 depends on C2; C4 on C3)
```

---

## 7. Testing & CI impact

- **Drop / rewrite (a2a-shell tests):** `test_executor_a2a.py`, `test_auth.py` (→ an
  auth-middleware-wraps-`main:app` test), `test_memory_read_a2a.py`, `test_plan_a2a.py`,
  `test_refine_a2a.py`, `test_plan_scaffold.py`. Their *behaviour* is already covered on the ADK path
  by `test_adk_kga.py` / `test_adk_tpd.py` / `test_adk_foundation.py` — confirm the assertions carried
  over before deleting.
- **Keep unchanged (the value gates):** the equivalence suite (v2 == v1 nodes/brief/scenarios), the
  copied-engine unit tests, `test_adk_eval*` (PQS/TPS + leak gate), `test_gateway.py` (MCP surface).
- **New:** provider-registry test (`get_provider()` maps the env → `VertexClaudeProvider`; unknown →
  error), the I8 grep gate, a `main:app`-boots smoke test.
- **CI:** the `[bridge]`/`[dev]`/`[eval]` extras are unchanged; the deterministic PR gate needs no
  judge model (as today).

---

## 8. Risks, open `[verify @2.x]` items, rollback

- **R-a — get_fast_api_app A2A parity.** The hand-built `a2a_card.py` skills/message endpoint are
  replaced by whatever `get_fast_api_app(a2a=True)` generates. **Verify** the gateway's `BridgeSession`
  reaches the per-agent message endpoint at the served path, and that the MCP tool names (from
  `register_tools`, unchanged) still satisfy I4. *Mitigation:* tool-parity test in C4; the tool names
  come from `register_tools`, not from A2A skills, so parity is structurally preserved.
- **R-b — auth under get_fast_api_app.** It ships no bearer. *Mitigation:* relocate (don't delete)
  `BearerAuthMiddleware` and wrap `main:app` (C3/C4); the gateway also gates inbound with
  `GATEWAY_BEARER_TOKEN`. Do **not** delete the middleware in C3 without the wrap in place.
- **R-c — task durability.** The a2a `DatabaseTaskStore` is retired; **verify** `DatabaseSessionService`
  (`SESSION_SERVICE_URI`) persists the A2A task lifecycle under get_fast_api_app, or that the gateway
  no longer relies on server-side task persistence.
- **R-d — stable `context_id → session_id`.** Still the open item from `DECISIONS.md` — the bridge/gateway
  must pass a stable ADK `session_id` across gather→refine→define→implement. Applies unchanged.
- **Rollback.** Docs-only now → trivial. Post-execution: v1 is untouched; revert the cutover commits +
  restore the Dockerfile CMD to `<agent>.adk_app:app`. `VERTEX_*` unset still forces the deterministic
  path (I7).

---

## 9. Decision-record delta (D10–D13) — mirrored into `DECISIONS.md`

- **D10 — Model access via a `ModelProvider` interface; `VertexClaudeProvider` the sole impl; Gemini
  removed.** *Supersedes D5's "one-env-var Gemini switch".* Why: user decision — abstract, don't
  multiply backends; the interface is the future-model extension point. Consequence: I5 gotchas live in
  the provider; a `LocalClaudeProvider` is a registry entry away.
- **D11 — One ADK-native entrypoint (`main:app` = `get_fast_api_app`) + one MCP gateway.** *Extends/
  supersedes D8* (which kept per-agent `to_a2a` + per-agent bridges). Why: "collapse to ADK-native".
  Consequence: per-agent `adk_app.py`/`server.py`/`a2a_card.py` + standalone bridge launchers dropped;
  `register_tools` kept (the MCP surface).
- **D12 — Domain logic extracted from `executor/` into neutral modules; the `*Executor` a2a shells
  dropped.** *Completes the D6/D9 transition.* Why: the ADK agents reused functions trapped inside the
  a2a-coupled packages; extraction is the precondition for deleting the shells.
- **D13 — Bearer auth is a transport-neutral ASGI middleware wrapping `main:app`; `DatabaseSessionService`
  subsumes the a2a `DatabaseTaskStore`.** Why: get_fast_api_app has no auth and no separate task store.
  Consequence: `common/adk/auth.py` (relocated from `common/middlewares`); `SESSION_SERVICE_URI` is the
  one durable store.

---

## 10. Definition of done

1. `grep -ri gemini src/` empty; model reached only via `ModelProvider` (I8); `VertexClaudeProvider`
   the sole provider, registry pluggable.
2. No a2a-sdk shell in our packages: `card/taskstore/ops/executor.py/middlewares/serve.py` +
   per-agent `server.py/a2a_card.py/adk_app.py/executor/*` gone; domain logic in neutral modules.
3. `main:app` (get_fast_api_app, a2a=True, bearer-wrapped) is the one server; `python -m gateway` is
   local Claude's one MCP entry with the **same tool names** (I4).
4. Full suite green: equivalence (v2==v1), all invariant gates I1–I8, PQS/TPS + leak gate; the
   a2a-shell tests retired with coverage carried to the ADK path.
5. `test-agent-v1` untouched; every `[verify @2.x]` item in §8 resolved during execution.
```
```

---

## 11. C3+C5+C4 execution checklist (grounded, from the Plan pass)

Order keeps the tree import-consistent; delete (step 5) only after tests are repointed.

**Step 1 — relocate (done):** `common/adk/auth.py` = BearerAuthMiddleware (open-paths broadened to allow `/a2a/*/.well-known/`); drop `serve` re-export from `common/adk/__init__.py`.

**Step 2 — harness linchpin:** rewrite `tests/eval/harness.py` a2a-free — drop `_app`/`_send`/`_all_text` + the `a2a`/`a2a_card`/`executor` imports; drive the ADK KGA router via an in-process `Runner` (patch `knowledge_gathering.agents.gather_agent.{build_client,build_bank}`, `knowledge_gathering.agent.build_bank`, `common.adk.interrogation.build_bank`, `common.adk.tools.build_bank`), reply = joined event text. Keep RecordedAtlassianClient/recorded_client/env/derive_tiers/RunTrace/run_refine_offline.

**Step 3 — conftest fixtures:** add `adk_a2a_app(build_root_agent)` = `to_a2a(root, runner=Runner(InMemorySessionService))` (RPC `/`, card `/.well-known/agent-card.json`) as the drop-in for deleted `_app`; + `patch_bank`/`patch_client` helpers.

**Step 4 — repoint/rewrite tests** (see §3 table): DROP test_executor_a2a, test_refine_a2a, test_plan_a2a. REWRITE test_memory_read_a2a, test_auth, test_plan_scaffold, test_explore, test_hypothesize, test_ground_leads, eval/test_engine, eval/test_plan_engine, test_gateway (backend→adk_a2a_app; relax exact-question-id), test_common_bridge (backend swap + card). MINOR repoint: test_adk_eval (golden→test_evaluation.golden), test_adk_idioms (drop a2a_card lines), test_atlassian_search + test_loop (executor.gather→gather). `run_gather(ex,ctx,queue,text)` has NO neutral home → test the units (hypothesize_terms/ground_leads/expansion_round) directly or via GatherAgent.

**Step 5 — delete (§1 list):** common/{card,taskstore,ops,executor}.py, common/middlewares/, common/adk/serve.py; per agent server.py + a2a_card.py + adk_app.py + executor/; AND testing_agent/adk_app.py (4th adk_app).

**Step 6 — C4 wiring:** main.py += `app.add_middleware(BearerAuthMiddleware)`; Dockerfile CMD→`uvicorn main:app` + **`COPY main.py ./`**; pyproject drop the 3 `*-bridge` scripts (already broken) + add `gateway="gateway.__main__:main"` (wheel `packages` unchanged); .env.example gateway URLs→`/a2a/<pkg>/` (trailing slash).

**Gates:** `uvicorn main:app` boots, `/list-apps`=agents; `python -m gateway` same tool names; bearer 401; full suite green (minus DROP set); `grep -ri gemini src/` empty. **R-a** deployed A2A mount = `/a2a/<app_name>/` (httpx concatenates base+path; trailing slash required) — verify card filename `agent-card.json` `[verify @2.x]`. **R-c** confirm DatabaseSessionService subsumes the retired a2a DatabaseTaskStore `[verify @2.x]`. Keep `GOOGLE_GENAI_USE_VERTEXAI` bootstrap (test_adk_idioms asserts it).
