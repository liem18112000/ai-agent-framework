# code-skeletons — ADK stubs for test-agent-v2

Concrete stubs the [`IMPLEMENTATION-PLAN.md`](IMPLEMENTATION-PLAN.md) milestones fill in. These show
the *shape* (imports, signatures, wiring, the load-bearing gotchas) — not full implementations. ADK
imports marked **[verify @1.22]** may move across `google-adk` minors; confirm against the pin.

---

## A.0 — `common/adk/model.py` — Claude via LiteLlm (I5)

```python
"""One place to build the Claude-on-Vertex model, with the v1 gotchas preserved."""
from __future__ import annotations
import os
from google.adk.models.lite_llm import LiteLlm          # [verify @1.22]
from common.llm.vertex import vertex_config              # reused: (PROJECT, LOCATION, MODEL) | None

def claude_llm(*, max_tokens: int = 6000) -> LiteLlm | None:
    cfg = vertex_config()
    if cfg is None:                # I7: no Vertex → caller uses the heuristic path
        return None
    project, location, model = cfg
    # I5: thinking MUST stay disabled so the whole max_tokens budget is output (tight JSON contracts);
    # LiteLLM passes provider kwargs through. VERIFY a disabled-thinking request actually reaches Vertex.
    return LiteLlm(
        model=f"vertex_ai/{model}",
        vertex_project=project, vertex_location=location,
        max_tokens=max_tokens,
        thinking={"type": "disabled"},   # [verify @1.22] — exact kwarg name for the LiteLLM/Anthropic path
    )
```

## A.0 — `common/adk/services.py` — Runner + durable sessions

```python
from google.adk.runners import Runner                                   # [verify @1.22]
from google.adk.sessions import DatabaseSessionService, InMemorySessionService
from google.adk.artifacts import GcsArtifactService, InMemoryArtifactService
from common.db import get_engine          # reused: shared Cloud SQL engine (also backs pgvector)

def build_session_service():
    eng = get_engine()
    # DatabaseSessionService subsumes v1's A2A DatabaseTaskStore + the GCS state.json rehydration.
    return DatabaseSessionService(db_url=eng.url) if eng else InMemorySessionService()  # [verify ctor]

def build_runner(agent, *, app_name: str):
    return Runner(
        agent=agent, app_name=app_name,
        session_service=build_session_service(),
        artifact_service=_artifacts(),
        plugins=[LearnDrainPlugin(), LessonRecallPlugin()],   # §plugins
    )
```

## A.0 — `common/adk/plugins.py` — cross-cutting hooks (I2)

```python
from google.adk.plugins import BasePlugin                    # [verify @1.22]
from common import learn
from common.memory.pg.project import maybe_drain_index
from common.memory.factory import build_bank

class LearnDrainPlugin(BasePlugin):
    """v1's head-of-request work, now global (was copy-pasted in each executor)."""
    async def before_run_callback(self, *, invocation_context, **_):
        bank = build_bank()
        if learn.capture_enabled(_agent_prefix(invocation_context)):
            await asyncio.to_thread(learn.drain, bank, now=_now())   # off-path (I3)
        await maybe_drain_index(bank)                                # no-op under MEMORY_BACKEND=gcs

class LessonRecallPlugin(BasePlugin):
    """Inject grounded, scope='shared' lessons before the model call (B4/B5 — I2)."""
    async def before_model_callback(self, *, callback_context, llm_request, **_):
        ...  # recall_lessons(bank, seed_refs) → prepend under "don't re-learn these"
```

## A.0 — `common/adk/serve.py` — A2A exposure (replaces v1 server.py + card.py)

```python
from google.adk.a2a.utils.agent_to_a2a import to_a2a        # [verify @1.22] path
from common.middlewares import BearerAuthMiddleware          # reused verbatim
from common.ops import make_health_routes                    # reused verbatim

def serve(root_agent, required_env: tuple[str, ...], *, port: int = 8081):
    app = to_a2a(root_agent, port=port)          # auto-generates the AgentCard from the agent (I4)
    for r in make_health_routes(root_agent.name, "0.2.0", required_env):
        app.router.routes.append(r)              # /livez /readyz  ([verify] app type Starlette/FastAPI)
    app.add_middleware(BearerAuthMiddleware)     # same opaque-bearer scheme
    return app
```

## A.0 — `common/adk/interrogation.py` — the HITL base (Option B — I1, avoids R1)

Shared by KGA refine and TPD define. Checkpoints to session `state`; pauses by ending the invocation.

```python
from google.adk.agents import BaseAgent
from common.interrogate.loop import RefineSession          # reused engine
from common.interrogate.present import render_questions, extract_ctx

class InterrogationAgent(BaseAgent):
    def __init__(self, name, rounds, gen_agent, understand_agent, *, agent_prefix):
        super().__init__(name=name)
        self.rounds, self.gen, self.und, self.prefix = rounds, gen_agent, understand_agent, agent_prefix

    async def _run_async_impl(self, ctx):
        state = ctx.session.state
        bank = build_bank()
        sess = RefineSession.rehydrate_from(state, bank) if state.get("io_started") else \
               RefineSession.begin(bank, extract_ctx(_user_text(ctx)), self.rounds)
        if answer := _user_answer(ctx):                     # continuation turn
            await sess.submit(answer)                       # ingest → insights (reused, deterministic)
        rnd = await asyncio.to_thread(sess.next_questions)  # 1 LLM call/round via gen_agent, or heuristic
        _save(state, sess)                                  # checkpoint loop state into session.state
        if rnd is None:
            result = await asyncio.to_thread(sess.finalize) # understanding brief (1 LLM call or heuristic)
            yield _event(ctx, summarize(result)); return    # invocation ends → "completed"
        yield _event(ctx, render_questions(rnd))            # invocation ends → next turn resumes (I1)
```

> The QuestionGen / Understanding / Brief / Scenarios `LlmAgent`s are thin: `LlmAgent(model=claude_llm(...),
> instruction=<the reused prompt from common/llm/prompts.py>, output_schema=<Questions|Understanding|…>)`
> with a heuristic fallback if the model yields zero parseable items (I5/I7).

---

## A1 — `knowledge_gathering/agents/gather_agent.py` (I1/I3/I5)

```python
from google.adk.agents import BaseAgent
from knowledge_gathering.executor.gather import run_gather   # reused crawl entrypoint (unchanged)

class GatherAgent(BaseAgent):
    async def _run_async_impl(self, ctx):
        # Re-trigger the v1 engine verbatim; offload the blocking BFS/codegraph work (I3 — Cloud Run /livez).
        summary = await asyncio.to_thread(run_gather_core, _seed_args(ctx), build_bank())
        yield _event(ctx, summary)     # crawl loop, budgets, fetchers, B0–B6, GCS upserts all unchanged (I1/I2)
```

## A1 — `knowledge_gathering/agent.py` (root) + `adk_app.py`

```python
# agent.py  [rewrite]
from google.adk.agents import BaseAgent          # a thin router, OR expose skills on one card
from .agents.gather_agent import GatherAgent
from .agents.refine_agent import build_refine_agent
from common.adk.tools import search_memory, get_note, search_lessons, veto_lesson

root_agent = KgaRoot(                              # name="knowledge-gathering"
    gather=GatherAgent(name="gather"),
    refine=build_refine_agent(),                   # InterrogationAgent(rounds=business/technical/qa,…)
    tools=[search_memory, get_note, search_lessons, veto_lesson],
)

# adk_app.py  [new]  (was server.py)
from common.adk.serve import serve
from .agent import root_agent
REQUIRED_ENV = ("ATLASSIAN_BASE_URL","ATLASSIAN_EMAIL","ATLASSIAN_API_TOKEN","GCS_BUCKET")
app = serve(root_agent, REQUIRED_ENV)
```

## A2 — `test_plan_definition/agents/implement_agent.py` (I3 — the detail gate)

```python
from google.adk.agents import BaseAgent
from test_plan_definition.implement.generate import implement_plan   # reused (unchanged)

class ImplementAgent(BaseAgent):
    async def _run_async_impl(self, ctx):
        detail = _wants_detail(ctx) or os.environ.get("TPD_LLM_DETAIL")   # I3: default OFF
        # Whole implement runs off the event loop; scenarios = the ONE default LLM call; test-data+steps
        # heuristic unless `detail`. Do NOT turn those LlmAgents on by default (re-creates ERROR_TIMEOUT).
        out = await asyncio.to_thread(implement_plan, build_bank(), _ctx_id(ctx), _run_id(ctx), _now(), detail)
        yield _event(ctx, summarize_implement(out))
```

`define_agent.py` = `build_refine_agent`'s sibling: `InterrogationAgent(rounds=("methodology","scope",
"metrics"), gen_agent=QuestionGen, understand_agent=Brief, agent_prefix="TPD")`. `approve_plan` is a
plain `FunctionTool` (deterministic status flip).

---

## B — `test_evaluation/eval/metrics/` — domain math as ADK custom metrics

```python
# one custom metric per v1 metric fn; ADK invokes it per EvalCase alongside the built-ins.
from google.adk.evaluation import Evaluator            # [verify @1.22] base/registry name
from test_evaluation.metrics import node_overlap, pqs  # reused math (unchanged)

class HardNegativeLeak(Evaluator):                     # threshold 0 in test_config.json — a real fail
    def evaluate(self, eval_case, invocation):
        gt = eval_case.custom                           # relevant/ must_not_retrieve etc. ride in `custom`
        s = node_overlap.retrieval_scores(_retrieved(invocation), gt["relevant_node_ids"],
                                          gt["must_not_retrieve_ids"])
        return _metric(len(s.leaked))                   # 0 == pass

class PqsScore(Evaluator): ...   # assembles the 5 components; `trajectory` now from native metric
```

```jsonc
// test_config.json  (criteria + thresholds)
{ "criteria": {
    "tool_trajectory_avg_score": 1.0,
    "hard_negative_leak": 0,
    "pqs_score": 0.70, "tps_score": 0.70,
    "hallucinations_v1": 0.8,                       // nightly, judge = Claude via LiteLlm
    "rubric_based_final_response_quality_v1": 0.7  // the semantic-rubric catalog finally runs
} }
```

Golden `golden/*.json` / `golden_plans/*.json` → `evalsets/*.evalset.json` (EvalCase: user_content +
expected tool-trajectory + reference; domain fields in `custom`). The runtime `evaluate_pack`/
`evaluate_plan` MCP tools call the **same** metric implementations (one codebase, two entry points).

---

## pyproject.toml — dependency delta (M0)

```toml
dependencies = [
  # ... all v1 runtime deps (a2a-sdk kept: to_a2a's A2A layer + the reused bridge) ...
  "google-adk>=1.22",
  "litellm>=1.0",          # LiteLlm model routing for Claude on Vertex
]
# extras unchanged: [bridge] mcp ; [dev] pytest/ruff ; [eval] ragas/pandas/datasets/google-adk
```

## Dockerfile — the only change (M0/D)

```dockerfile
# bridge CMD unchanged. Agent CMD:
# v1:  uvicorn knowledge_gathering.server:app  --host 0.0.0.0 --port ${PORT}
# v2:  uvicorn knowledge_gathering.adk_app:app --host 0.0.0.0 --port ${PORT}
```
