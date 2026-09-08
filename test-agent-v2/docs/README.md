# test-agent-v2 / docs — the build guide

The **executable implementation plan** for the ADK rebuild. Where the repo-root
[`../../docs/adk-transform/`](../../docs/adk-transform/) is the *design* (why each mapping, the two
plans, the risk register), these docs are the *build order* (what to create, in what sequence, with
which test gate).

Read in this order:

1. [`IMPLEMENTATION-PLAN.md`](IMPLEMENTATION-PLAN.md) — objective, the **7 invariants** CI must
   protect, the target directory layout, the engine-reuse strategy, and the **phased milestones**
   (M0 → A0 spike → A.0 foundation → A1 KGA → A2 TPD → B evaluator → D deploy), each with files,
   test gates, and done-criteria.
2. [`code-skeletons.md`](code-skeletons.md) — concrete ADK stubs the milestones fill in
   (`common/adk/{model,services,plugins,serve,interrogation}.py`, the KGA/TPD agents, the evaluator
   custom metrics), with the load-bearing gotchas inline.
3. [`DECISIONS.md`](DECISIONS.md) — the decision record (D1–D9): where v2 deliberately diverges from
   the canonical ADK idioms, and why. Read before "fixing" a custom `BaseAgent`, the gated flow, or
   the Claude-via-LiteLlm default.
4. [`ENHANCEMENT-adk-idioms.md`](ENHANCEMENT-adk-idioms.md) — a follow-on proposal aligning v2 with
   the canonical `google/adk-samples` idioms (E1–E8): what to adopt (`agent.py`/`root_agent`+`adk web`,
   `Config`, plain-function tools, canonical `eval/`+`adk eval`, Agent-Engine deploy, an optional
   autonomous `AgentTool` coordinator) and what to consciously keep (custom `BaseAgent` routers,
   client-driven gating, Claude-via-LiteLlm), each with rationale.
5. [`ENHANCEMENT-adk-native-cutover.md`](ENHANCEMENT-adk-native-cutover.md) — the **next enhancement**
   (milestones C0–C6, decisions D10–D13): finish the migration by going ADK-native end to end — remove
   the a2a-sdk shells, drop the **Gemini** backend, and re-express model access as an extensible
   `ModelProvider` interface (Claude-on-Vertex the sole impl). Collapses serving to one `main:app`
   (`get_fast_api_app`) + one MCP gateway.

**Start here:** milestone **A0 — the HITL pause/resume spike** (de-risks the one real unknown before
any bulk porting). See `IMPLEMENTATION-PLAN.md` §4.

Traceability: every milestone maps back to a section of the design docs (`01`–`04`) and forward to
an invariant (I1–I7). Nothing in this plan changes `test-agent-v1/`.
