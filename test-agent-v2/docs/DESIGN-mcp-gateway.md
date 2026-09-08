# DESIGN — single MCP gateway + A2A-native inter-agent comms (v2)

**Status:** proposed (for review before build). **Date:** 2026-09-08.

## Goal (from the ask)
1. **One MCP gateway** = the single endpoint local Claude connects to (not 3 separate MCP servers).
2. When an **agent/sub-agent talks to another agent, it does so natively over A2A** — no in-process
   cross-agent coupling.

## Current architecture (what we deployed)
- **3 Cloud Run services** — `knowledge-gathering-agent-v2`, `test-plan-definition-agent-v2`,
  `test-evaluation-agent-v2`. Each = **2 containers**:
  - `agent` — `uvicorn <pkg>.adk_app:app` (ADK `to_a2a`), A2A on `:8081`.
  - `bridge` — `python -m <pkg>.bridge` (MCP→A2A), Streamable-HTTP on `:8080`, bearer-gated.
- **3 MCP endpoints**; Claude registers all three (`install-mcp` → `/mcp` × 3).
- Each bridge (`<pkg>/bridge/mcp_server.py`) = one `MCPServer` + one `BridgeSession` (A2A client to
  that agent via `<PKG>_A2A_URL` + `A2A_BEARER_TOKEN`) + `@mcp.tool()` forwarders.
- Shared plumbing already exists in `common/bridge/`: `BridgeSession` (A2A client + multi-turn task
  map), `build_http_app(mcp, env_prefix)` (bearer gate + Streamable-HTTP).
- The gated pipeline is **Claude-orchestrated**: Claude calls each agent's tools with a shared
  `context_id`; the agents do **not** call each other. The **autonomous** path
  (`testing_agent/agent.py`) is an ADK **`SequentialAgent`** with KGA/TPD/TEV as **in-process
  sub-agents** — that's the deprecation warning (`SequentialAgent` → `Workflow`) and it's *not* A2A.

## Target architecture

![Target architecture — one MCP gateway, A2A-native agents](DESIGN-mcp-gateway-target.png)

*(source: `DESIGN-mcp-gateway-target.excalidraw`)*

```
Claude Code ──MCP(1 endpoint, bearer)──▶  MCP GATEWAY (new service)
                                             │  routes each tool call over A2A
                        ┌────────────────────┼────────────────────┐
                        ▼ A2A                 ▼ A2A                 ▼ A2A
              knowledge-gathering-v2   test-plan-definition-v2   test-evaluation-v2
              (A2A-only, no bridge)    (A2A-only)                (A2A-only)
                        ▲                                            
                        └── autonomous coordinator (optional) reaches agents via RemoteA2aAgent (A2A)
```

- **Gateway** = one `MCPServer("testing-agent-gateway")` holding **three `BridgeSession`s**
  (`KGA_A2A_URL`, `TPD_A2A_URL`, `TEV_A2A_URL`), exposing the **union** of all tools, each bound to
  its agent's session. Bearer-gated with a single `GATEWAY_BEARER_TOKEN`. This is exactly today's
  bridge pattern with 3 upstreams instead of 1 → heavy reuse of `common/bridge`.
- **Agents become A2A-only** (drop the `bridge` sidecar). They already serve A2A via `adk_app`.
- **Inter-agent = A2A**: the autonomous coordinator reaches KGA/TPD/TEV via ADK **`RemoteA2aAgent`**
  (A2A client) instead of in-process sub-agents.

## Design details

### 1. Reuse — refactor `mcp_server.py` into a tool-registration factory
Each `<pkg>/bridge/mcp_server.py` currently binds tools to a module-level `mcp` + `_session`. Refactor to:
```python
def register_tools(mcp: MCPServer, session: BridgeSession) -> None:
    @mcp.tool()
    async def gather_knowledge(...): ...   # bound to the passed-in session
    ...
```
- **Standalone bridge** (kept working / for local stdio dev): `mcp = MCPServer(...); register_tools(mcp, BridgeSession(URL, TOKEN))`.
- **Gateway**: one `mcp`; call `kga.register_tools(mcp, kga_session)`, `tpd.register_tools(...)`,
  `tev.register_tools(...)`.

### 2. Tool-name collisions
KGA + TPD + TEV each define `send_raw` and `agent_card`; KGA/TPD each define a `test` prompt.
Resolve in the gateway:
- Expose **one** `agent_card()` that returns all three cards; **one** `test` prompt (KGA's).
- Namespace the escape hatches: `send_raw_kga` / `send_raw_tpd` / `send_raw_tev` (or drop from the
  gateway — they're rarely used).
- All the *real* tools are already unique: `gather_knowledge, gather_codebase, refine, get_questions,
  get_understanding, search_memory, get_note, search_lessons, veto_lesson, approve` (KGA);
  `define_plan, approve_plan, implement_plan, get_plan, get_scenarios` (TPD);
  `evaluate_pack, evaluate_plan` (TEV). No conflicts.
- Merge the three `instructions` blocks into one gateway instruction (pipeline + confirm-gate rules).

### 3. Deployment topology — RECOMMENDED: gateway as a 4th service
- **`mcp-gateway-v2`** service: 1 container (`python -m gateway` / `uvicorn`), Streamable-HTTP `/mcp`
  on `:8080`, public + `GATEWAY_BEARER_TOKEN`. Env: `KGA_A2A_URL`, `TPD_A2A_URL`, `TEV_A2A_URL`,
  `A2A_BEARER_TOKEN`.
- **3 agent services**: single-container (agent only), A2A on `:8080`. Keep them public +
  `A2A_BEARER_TOKEN` (simplest reachability) — the gateway calls them with the bearer. (Hardening
  option later: `ingress=internal` + Cloud Run ID-token auth so agents aren't publicly reachable.)
- **Alternative (merged):** one service, 4 containers (3 agents on localhost:8081/2/3 + gateway on
  8080). Simpler single deploy + localhost A2A, but couples scaling/lifecycle. *Not recommended* —
  loses the independent-service benefit the split was built for.

### 4. `SequentialAgent` deprecation + autonomous coordinator
- The `SequentialAgent` in `testing_agent/agent.py` is the **root** (not an `LlmAgent` sub-agent), so
  the "Workflow cannot be an LlmAgent sub-agent" caveat doesn't block migrating it.
- Two coupled changes for the autonomous path:
  - **A2A-native:** replace the in-process KGA/TPD/TEV sub-agents with `RemoteA2aAgent(agent_card_url=<agent A2A>)`.
  - **Deprecation:** migrate the `SequentialAgent` root to `Workflow` *iff* `Workflow` accepts
    `RemoteA2aAgent` children on the pinned `google-adk` (verify in a 5-min spike). If not, keep
    `SequentialAgent` for now (warning is non-breaking) and revisit.
- Note: the autonomous coordinator is **not currently deployed** (only KGA/TPD/TEV are in terraform).
  So this refactor is independent of getting the gateway live — can be a later phase.

### 5. Terraform changes (`deployments/test-agent-v2`)
- New `module "gateway"` (or a top-level service): image = same `test-agent-v2` image, command =
  gateway entrypoint; env `*_A2A_URL` = the three agents' own service URLs; `GATEWAY_BEARER_TOKEN`
  secret (`kga-v2-gateway-bearer-token`).
- Drop the `bridge` sidecar container from `module.kga/tpd/tev` (agents become single-container).
- Outputs: replace `bridge_url/tpd_bridge_url/tev_bridge_url` with a single `gateway_url`.
- `install-mcp.{sh,cmd}`: register **one** server (`testing-agent` → `$(terraform output -raw gateway_url)`).
- `deploy.sh`: unchanged in shape (already hardened: repo → build → apply); one more secret version.

## Migration phases

> **Status (2026-09-08): G1 + G2 implemented** (gateway code + `register_tools` refactor + subagents
> split + terraform: agents A2A-only, `mcp-gateway-v2` service, single `gateway_bearer` secret,
> `gateway_url` output, `install-mcp` → one endpoint; standalone per-agent bridges deleted). Tests +
> `terraform validate` green. **G3 = deploy** (`./deploy.sh` then `./install-mcp.sh`). **G4 deferred.**

- **G1** — gateway code: `register_tools` factory refactor in the 3 `mcp_server.py`; new `gateway`
  package composing them; offline tests (reuse the bridge tests' in-process A2A client injection).
- **G2** — terraform: add `mcp-gateway-v2`; make agents A2A-only; secret + outputs; `install-mcp`.
- **G3** — deploy (hardened `deploy.sh`), register the one endpoint, verify end-to-end via Claude.
- **G4** (independent) — autonomous coordinator → `RemoteA2aAgent`; `SequentialAgent`→`Workflow` spike.

## Risks / open questions
- **Auth between gateway and agents:** bearer (simple, public agents) vs Cloud Run internal + ID
  token (private agents, more setup). Proposal: bearer first, harden later.
- **Multi-turn task state:** `BridgeSession` keeps a `context_id→task_id` map per process. One gateway
  process now holds state for all three upstreams — fine (separate sessions), but confirm statefulness
  under `*_STATELESS` / multiple gateway instances (pin `min_instances`≥1 or run stateless + rely on
  A2A context_id, as today).
- **Single point of entry:** the gateway is now a SPOF for Claude access — acceptable (it's the ask);
  keep it thin (pure routing, no business logic).
- **`Workflow` viability** with `RemoteA2aAgent` children — needs a quick spike before committing G4.

## Decisions (RESOLVED 2026-09-08)
1. Topology: **4th gateway service** (`mcp-gateway-v2`) fronting the 3 A2A agents. ✅
2. Agent reachability: **public + A2A bearer** (harden to private later). ✅
3. Scope: **G1–G3 now** (gateway live); **G4** (RemoteA2aAgent coordinator + SequentialAgent→Workflow)
   deferred to a follow-up. ✅
