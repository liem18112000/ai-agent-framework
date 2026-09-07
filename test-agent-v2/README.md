# test-agent-v2 — the ADK version (implementation target)

This directory is where the **Google ADK (`google-adk`) rebuild** of the Testing Agent is
implemented. It starts empty; build it per the plan.

- **▶ Build guide (start here):** [`docs/IMPLEMENTATION-PLAN.md`](docs/IMPLEMENTATION-PLAN.md) — the
  detailed, executable plan (invariants, directory layout, phased milestones, test gates) +
  [`docs/code-skeletons.md`](docs/code-skeletons.md) (concrete ADK stubs).

- **Plan & mapping:** [`../docs/adk-transform/`](../docs/adk-transform/) — read `README.md` first,
  then `01-mapping.md` (component mapping), `02-plan-testing-agents.md` (Plan A: KGA + TPD),
  `03-plan-test-evaluation.md` (Plan B: the evaluator on `adk eval`), `04-roadmap-risks.md`.
- **Baseline being transferred from:** [`../test-agent-v1/`](../test-agent-v1/) — the current
  a2a-sdk + FastAPI code. ~70% of it (the framework-neutral `common/*` engine) is reused unchanged;
  only the a2a-sdk shell is replaced (see `02` §A.0 and the mapping ledger in `01`).
- **Deployment:** to be created at `../deployments/test-agent-v2/` (copy of
  `../deployments/test-agent-v1/`, own terraform state) — see `02` §A.3.

First implementation step per the roadmap: **A0 — the HITL pause/resume spike** (de-risk
`LongRunningFunctionTool`-in-`SequentialAgent` vs. the custom-agent state-checkpoint default) before
the shared foundation (`common/adk/`) and the per-agent graphs.
