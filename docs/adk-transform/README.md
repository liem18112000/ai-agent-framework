# ADK Transform — export

Transform the **Testing Agent** stack from its hand-rolled `a2a-sdk` + FastAPI shape onto
**Google's Agent Development Kit (ADK, `google-adk` ≥ 1.22, `adk-python`)**, without losing the
determinism, the two-tier memory, the de-bias gates, or the Cloud Run deployment the team already
runs in production.

This folder is **design/plan documentation only** — no code is changed by reading it. It is
detailed enough to execute milestone-by-milestone later.

---

## Paths & versions

The repo is now split by agent version. Every path in these docs follows this convention:

| Role | Location |
|------|----------|
| **Current code** — a2a-sdk + FastAPI, the baseline these docs describe | `test-agent-v1/` |
| **ADK implementation target** — where Plan A & B code is built | `test-agent-v2/` |
| **v1 deployment** — terraform / Cloud Run, unchanged | `deployments/test-agent-v1/` |
| **v2 deployment** — to be created for the ADK build | `deployments/test-agent-v2/` |
| **These migration docs** | `docs/adk-transform/` (repo root) |

Package-relative paths (`common/…`, `src/knowledge_gathering/…`) name the code layout *inside* an
agent project: read them under `test-agent-v1/` when a passage describes today's baseline, and
**create them under `test-agent-v2/`** when it describes the ADK build. `test-agent-v2/` starts
empty; the ~70% reused engine is lifted from `test-agent-v1/` (see
[`02`](02-plan-testing-agents.md)).

---

## Scope — what transfers, and the one exception

The user's instruction: *"transfer all testing agent + (exception for the test-evaluation —
make separate plan for apply the same or better method)."* So the export is **two plans**:

| Plan | Agents | Method | Doc |
|------|--------|--------|-----|
| **A — Testing agents** | `knowledge-gathering` (KGA) + `test-plan-definition` (TPD), on the shared `common` engine | Re-host the deterministic pipelines as **ADK workflow-agent graphs** (`SequentialAgent`/`LoopAgent` + custom `BaseAgent` + `LlmAgent`), reuse the neutral engine as ADK tools/services, expose over A2A with `to_a2a()`. | [`02-plan-testing-agents.md`](02-plan-testing-agents.md) |
| **B — Evaluator (the exception)** | `test-evaluation` (Step 5 scorer) | **"Same or better":** rebuild it on ADK's **native evaluation framework** (`AgentEvaluator`, evalsets, `tool_trajectory_avg_score` / `hallucinations_v1` / `rubric_based_*`) with the domain metrics (PQS/TPS, leak gate, coverage matrix) as **ADK custom metrics** — turning today's *aspirational* ADK references into real `google-adk` calls. | [`03-plan-test-evaluation.md`](03-plan-test-evaluation.md) |

Why the split matters: the evaluator is a *different kind of thing*. KGA/TPD are agents you **run**;
the evaluator **scores** agents — and ADK ships a first-class harness for exactly that. Porting it
"the same way" as KGA/TPD would waste the best part of adopting ADK. So it gets its own plan that
leans on `adk eval` instead of the agent-runtime primitives.

---

## The two decisions already made

1. **Deliverable = design/plan docs only.** Plans + mapping tables + a phased roadmap + a
   target-architecture diagram. No `src/` code, no commits yet.
2. **Model backend = keep Claude via LiteLlm.** Every LlmAgent uses
   `LiteLlm(model="vertex_ai/claude-sonnet-5")` so today's Claude Sonnet 5 behavior is preserved;
   ADK's Gemini-first path is noted as an alternative but not the target. The one added cost is a
   LiteLLM abstraction hop over the direct `anthropic[vertex]` client used today (see the gotchas
   in [`01-mapping.md`](01-mapping.md#7-claude-via-litellm--the-hop-and-its-gotchas)).

---

## Relationship to the earlier "ADK vs current stack" analysis

`test-agent-v1/docs/adk-vs-current-stack.excalidraw/.png` already argued a **selective hybrid**: keep KGA/TPD as
`a2a-sdk`-direct, adopt ADK only for one genuinely LLM-driven new agent. **This export deliberately
goes further** — a full transfer of both agents — because that is what was asked. The honest
tradeoff the diagram flagged still stands and is preserved here rather than buried:

- A full transfer is mostly **re-hosting a deterministic engine**, not unlocking an autonomous loop.
  The real wins are the *cross-cutting services* ADK gives you for free (durable sessions, callbacks/
  plugins, artifacts, tracing, `adk web`, and — for the evaluator — `adk eval`), not the agent loop.
- The costs are the **LiteLlm hop** and taking on ADK's release cadence + a couple of **known HITL
  resume bugs** (see the risk register). Those are why [`04-roadmap-risks.md`](04-roadmap-risks.md)
  front-loads a de-risking spike before any bulk porting.

Read [`01-mapping.md`](01-mapping.md) for where the transfer is pure re-host vs. a real upgrade.

---

## Read in this order

1. [`00-current-state.md`](00-current-state.md) — the baseline we transform **from** (the shape,
   the LLM-vs-deterministic split, state/persistence, deployment topology).
2. [`01-mapping.md`](01-mapping.md) — ADK primer + the **master component-mapping table** + the
   reuse-vs-replace ledger + the cross-cutting design decisions (determinism, HITL, state, memory,
   callbacks, model).
3. [`02-plan-testing-agents.md`](02-plan-testing-agents.md) — **Plan A**, per agent, with the target
   agent graph and a phased milestone list.
4. [`03-plan-test-evaluation.md`](03-plan-test-evaluation.md) — **Plan B**, the evaluator on ADK eval.
5. [`04-roadmap-risks.md`](04-roadmap-risks.md) — consolidated sequencing, effort, the risk register,
   and rollback.
6. `adk-transform-target.excalidraw/.png` — the target-architecture picture.

---

## One-paragraph summary

Both testing agents keep their exact deterministic engines (`common/{memory,learn,interrogate,llm,
atlassian,codegraph,extract}`) — those import no framework and become **ADK tools/services
unchanged**. What gets replaced is the thin `a2a-sdk` shell (`server.py`, `card.py`, `executor/*`,
the `DatabaseTaskStore`, `common/{card,taskstore,executor,ops,middlewares,bridge}`): each agent
becomes an ADK agent graph, its multi-turn interrogation becomes an ADK long-running-tool / custom-
agent pause-resume backed by a **`DatabaseSessionService`** (which subsumes *both* today's A2A task
store *and* the GCS `state.json` rehydration), and the whole thing is re-exposed over A2A with
`to_a2a()` behind the **unchanged** Cloud Run bridge+sidecar topology. The evaluator instead becomes
an `adk eval` harness whose golden sets are ADK evalsets and whose PQS/TPS composites are ADK custom
metrics. The MCP tool surface Claude Code talks to does **not** change.
