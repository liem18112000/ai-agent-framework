# 04 · Roadmap, effort, risks, rollback

Consolidated sequencing across Plan A ([`02`](02-plan-testing-agents.md)) and Plan B
([`03`](03-plan-test-evaluation.md)), the risk register, and how to back out. Effort is
**relative T-shirt sizing**, not calendar time.

---

## 1. Sequencing

The safe order front-loads a de-risking spike, then goes agent-by-agent behind the unchanged bridge
so each step ships independently and rolls back independently.

```
A0  SPIKE (HITL pause/resume)  ─┐
                                ├─▶  Shared foundation (A.0)  ─▶  KGA (A1)  ─▶  TPD (A2)  ─▶  Evaluator (B)
                                │        (common/adk/, services, plugins, model)
(prove Option B on ADK before   │
 committing the shell rewrite)  ─┘
```

| Phase | What | Size | Gate to proceed |
|-------|------|------|-----------------|
| **A0 — Spike** | Prove the HITL pause/resume on ADK: one `InterrogationAgent` over ADK session state (Option B), + a probe of `LongRunningFunctionTool`-in-`SequentialAgent` (Option A) to confirm/deny the known resume bugs at 1.22. | S | Option B round-trips a 3-round interrogation across "turns" with state intact |
| **A.0 — Foundation** | `common/adk/` (model, services, plugins, serve, tools); lift `build_bank`; skill-parity test. | M | `to_a2a` app serves a trivial agent behind the bridge; card advertises expected skills |
| **A1 — KGA** | `GatherAgent` + read tools → `RefineAgent` → DB sessions + plugins → deploy. | L | A.5 acceptance for KGA; offline harness equivalent |
| **A2 — TPD** | `InterrogationAgent` reuse (`DefineAgent`) → `ImplementAgent` (detail-gate!) → deploy. | M | A.5 acceptance for TPD; `implement` = 1 LLM call, within timeout |
| **B — Evaluator** | evalsets → custom metrics → native trajectory → judged tier → runtime re-point. | M | B.7 acceptance; PQS/TPS reproduce today's numbers |

Rationale for the order: the **spike is cheap insurance** against the one genuinely uncertain thing
(HITL-on-ADK). KGA before TPD because KGA's `RefineAgent` produces the reusable `InterrogationAgent`
base TPD's `DefineAgent` then consumes. The evaluator last because it *judges* the migration — Plan B
is the objective proof Plan A didn't regress.

## 2. Effort split (relative)

- **~70% reuse** — the neutral engine (`memory/learn/interrogate/llm/atlassian/codegraph/extract`)
  moves unchanged. Most "work" is wrapping, not writing.
- **~30% new/rewrite** — `common/adk/`, the per-agent graphs (custom BaseAgents + LlmAgents), the
  state migration to `SessionService`, and the evalset/custom-metric layer.
- Heaviest single items: (1) the HITL state migration (A0+A1-b), (2) the evaluator custom-metric
  registration (B-b), (3) validating the LiteLlm thinking-disabled + max_tokens path (cross-cutting).

## 3. Risk register

| # | Risk | Likelihood · Impact | Mitigation |
|---|------|---------------------|------------|
| R1 | **HITL resume bugs** — `LongRunningFunctionTool` nested in `SequentialAgent` re-executes sub-agents / fails to resume (adk-python #3348/#5349/#3184/#5064). Refine/define are exactly this shape. | Med · High | **A0 spike first.** Default to **Option B** (custom-agent state checkpoint), which sidesteps LRO-in-Sequential entirely. Adopt Option A only if the spike clears it. [verify @1.22] |
| R2 | **LiteLlm silently re-enables thinking** or drops the max_tokens tuning → truncated JSON / mid-array parse failures (the 1500→6000 incident) / budget eaten by thinking. | Med · High | Centralize in `claude_llm()`; add a test asserting a disabled-thinking request reaches Vertex and a full-length questions array parses. Keep `loads_array` + heuristic fallback. |
| R3 | **Blocking engine work on the event loop** under a custom BaseAgent → Cloud Run `/livez` starve → `ERROR_TIMEOUT` (the exact prior incident). | Med · High | `asyncio.to_thread` around every crawl/codegraph/heuristic block inside BaseAgents; keep the 600s request timeout; keep `implement` = 1 LLM call by default. |
| R4 | **A B-gate regresses** in the rewrite — a hard-negative leaks, or recall stops being grounded/`scope='shared'`. | Low · High | B-gates live in reused modules (not rewritten). Plan B's `hard_negative_leak==0` custom metric gates every eval run. Bleed-fixture parity test in A1/A2. |
| R5 | **Session-state migration loses continuity** — mid-flight refine/define sessions break on cutover. | Low · Med | New sessions only on the new store; no in-flight migration (sessions are short-lived). Deploy per-agent during a quiet window; the bridge/other agents are untouched. |
| R6 | **ADK release cadence / API churn** across 1.x (evalset schema, `to_a2a` path, custom-metric API). | Med · Med | Pin `google-adk` exactly; snapshot the evalset schema at B-a; mark every version-sensitive call **[verify @1.22]**; a thin `common/adk/` insulates call sites. |
| R7 | **Judge portability** — ADK judged metrics are Gemini-first; Claude-via-LiteLlm judge behaves differently. | Med · Low | Deterministic gate stays authoritative; judged scores advisory until calibrated (B.8). |
| R8 | **Card/skill drift** breaks the unchanged bridge (auto-generated card ≠ expected skills). | Low · Med | Skill-parity test in A.0; or supply a hand-built `agent_card=` to `to_a2a`. |
| R9 | **Scope creep into an LLM-driven loop** — someone "upgrades" a workflow agent into an autonomous one, discarding B0–B6. | Low · High | Explicit non-goal in `01` §3 and `02` A.4. Autonomy is a *separate future agent*, not this transfer. |

## 4. Rollback

- **Per-agent, per-container.** Each agent's cutover is a single change to its **agent container**
  start command + image tag. Revert that one field and the pre-migration `a2a-sdk` server is back.
- **Data is untouched.** GCS bank layout, pgvector schema, and Cloud SQL are unchanged; a
  `DatabaseSessionService` adds tables beside the existing ones — rolling back just stops using them.
- **The bridge and the other two agents keep running** throughout (independent services). There is no
  big-bang cutover; at any moment 0, 1, 2, or 3 agents can be on ADK.
- **Kill switch**: `VERTEX_*` unset still forces the fully-deterministic heuristic path in the reused
  engine, so an LLM/LiteLlm problem degrades rather than breaks (as today).

## 5. Definition of done (whole transform)

1. KGA, TPD served as ADK agent graphs via `to_a2a`, behind the unchanged bridge; MCP surface identical.
2. `DatabaseSessionService` is the single durable session store (A2A task store + GCS `state.json` +
   `_sessions` map all retired).
3. The evaluator runs on `adk eval` with real `google-adk`; PQS/TPS reproduce today's numbers; the
   leak gate is a first-class eval failure; the semantic-rubric catalog runs.
4. All B0–B6 gates verified intact; `implement` default = 1 LLM call within timeout.
5. Every version-sensitive ADK call has been confirmed against the pinned `google-adk` (the
   **[verify @1.22]** markers resolved).
