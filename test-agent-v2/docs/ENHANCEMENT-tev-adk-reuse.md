# Enhancement — ADK reuse for the evaluator (`test_evaluation`): provider-sourced judge + the native judged tier

The **executable plan** for the "reuse ADK more, on the agent aspect" review of `test_evaluation`
(TEV). **The headline finding is a negative one:** the KGA/TPD pattern from
[`ENHANCEMENT-explore-llmagent.md`](ENHANCEMENT-explore-llmagent.md) /
[`ENHANCEMENT-tpd-llmagent.md`](ENHANCEMENT-tpd-llmagent.md) — "convert raw-Vertex generators into
`LlmAgent`s" — **does not apply here and must not be applied.** TEV has **no raw-Vertex generators**
(grep for `llm.vertex`/`complete(` in `src/test_evaluation` → none), its live scorer is **deliberately
deterministic**, and it is already the agent that reuses ADK the *most* (native `adk eval`). What is
left is a **smaller, different** surface: route the *judge* model through the provider (I8) and realize
the **ADK-native judged tier** that the code already names but leaves unwired.

> **Status: IMPLEMENTED 2026-09-08 (D17) — V0–V4.** Provider-sourced judge factory (`eval/judge.py`);
> RAGAS routed through it (no OpenAI default); `judge_semantic` wired as an opt-in judged rubric;
> ADK-native `JUDGED_METRICS` in `eval/config.py`+`runner.py`, creds-gated. **Live scorer stays
> deterministic + LLM-free** (zero-LLM-call assertion). Live RAGAS tier needs `langchain-community`/
> `langchain-google-vertexai` in the `eval` extra (never imported offline; follow-up). Full suite:
> 388 passed, 14 skipped.

Cross-refs: decisions **D1, D7, D10** and the recorded **"Open: Judged eval tier
(`hallucinations_v1`/`rubric_based_*`) with a judge model"** ([`DECISIONS.md`](DECISIONS.md));
invariants **I1 (determinism), I8 (model only via the provider)**
([`IMPLEMENTATION-PLAN.md`](IMPLEMENTATION-PLAN.md)); the model provider (C1/D10).

---

## 0. Objective & the key finding

A scorer's value is **reproducibility**: PQS/TPS must be deterministic, read-only, and fast so the same
pack/plan always scores the same. So the objective here is **not** to make the evaluator "more agentic"
— it is to (a) make any LLM the evaluator *does* use come from the one configured provider (I8), and
(b) reuse ADK's **native judged-metric harness** for the judged tier instead of a bespoke path — while
keeping the **default live scoring path LLM-free and deterministic**.

**Do not agent-ify the scoring.** That is the load-bearing non-goal (see §8).

---

## 1. Current state (grounded inventory)

TEV has three distinct layers; only one touches an LLM, and it is injected + offline:

### 1a. The live scorer — fully deterministic (and must stay so)
`EvaluatorAgent` (custom `BaseAgent`) dispatches `evaluate_pack` / `evaluate_plan` via
`asyncio.to_thread`. Both engines score with **deterministic** metrics only:

- retrieval `node_overlap` (precision/recall + hard-negative leak gate), `coverage`, `mutation`
  (fault-class), `oracle`, `placeholders`, `entities`, `topic`, `noise`, `gherkin_lint`.
- the wired rubrics `cites_only_real_ids` / `no_invented_urls` are **regex** (`_JIRA_KEY`, `_URL`) —
  **not** LLM. The deployed A2A scoring path makes **zero** model calls.

### 1b. The LLM-judged parts — injected + offline-only (not in the live path)
- `metrics/ragas_judge.py::judge(…, llm=None, embeddings=None)` — RAGAS Faithfulness + Answer
  Relevancy. The model is **injected**; it is called **only** from the out-of-band pytest harness
  (`tests/eval/test_eval_judged.py`, `test_eval_tpd_judged.py`) and **skips** when the `ragas` extra is
  absent. RAGAS defaults to **OpenAI** if no `llm` is passed — i.e. *not* the configured Claude.
- `metrics/rubrics.py::judge_semantic(understanding, judge)` — two semantic rubrics
  (`names_the_ac`, `declares_gaps_honestly`) via an **injected** `judge(question, text) -> bool`.
  **`judge_semantic` is defined but called nowhere in `src`** — an unwired seam.

### 1c. The eval framework — already ADK-native (`adk eval`, "Plan B")
This is where TEV *already* reuses ADK heavily:
- `eval/adk_metrics.py` wraps the deterministic engines as ADK **custom-metric functions**
  (`EvalMetric`, `EvaluationResult`, `PerInvocationResult`, `EvalStatus`): `pqs_score`,
  `hard_negative_leak`, `tps_score`, `must_not_scope_leak`.
- `eval/evalset.py` builds ADK `EvalSet`/`EvalCase`/`Invocation` from `golden/`.
- `eval/runner.py` runs ADK's `AgentEvaluator.evaluate(...)`.
- `eval/config.py` declares the metric criteria **and names the native judged tier**:
  `JUDGED_METRICS = ("hallucinations_v1", "rubric_based_final_response_quality_v1",
  "final_response_match_v2")` — **ADK's built-in LLM-judged metrics, listed but not wired.**

Same as KGA/TPD: `agent_model()` has **zero callers** in `src/test_evaluation`.

---

## 2. Where ADK can be reused more (the real, smaller surface)

Ranked; both items are **opt-in / offline** and never touch the deterministic default path.

**① Provider-sourced judge + embeddings (I8) — closest analog to the KGA/TPD win.**
When RAGAS (`ragas_judge.judge`) or `judge_semantic` runs, the `llm`/`embeddings`/`judge` should be
built from **`agent_model()` / the `ModelProvider`** (Claude-on-Vertex), not RAGAS's default OpenAI or
an ad-hoc client injected only by tests. Add a small `test_evaluation/eval/judge.py` factory —
`build_judge()` / `build_ragas_llm()` — that sources the model from the provider, so every LLM-judged
metric uses the one configured model. This gives the provider its first TEV consumer without adding any
call to the live scorer.

**② Realize the ADK-native judged tier (`JUDGED_METRICS`) — "reuse ADK more" proper.**
`eval/config.py` already names ADK's native judged metrics. Wire them into `eval/config.py` +
`eval/runner.py` so the judged tier runs through **ADK's own LLM-judged evaluators** rather than a
hand-maintained RAGAS path. The two `SEMANTIC_RUBRICS` map naturally onto ADK's
`rubric_based_final_response_quality_v1` (pass the rubric prompts as its criteria);
`hallucinations_v1` subsumes the fabrication intent behind `cites_only_real_ids`/`no_invented_urls`
at the semantic level. This operationalizes the recorded **"Open: Judged eval tier"** decision.

**③ Wire `judge_semantic` as an opt-in judged rubric (not the live default).**
The defined-but-unwired `judge_semantic` becomes reachable **only** in the judged tier (V-gated /
offline), driven by the provider-sourced judge from ①. It must never enter `evaluate_pack`'s default.

---

## 3. Decision & reconciliations

### D17 (proposed) — TEV's judged tier runs through the provider + ADK-native judged metrics; the live scorer stays deterministic
- **Decision:** add a provider-sourced judge/embeddings factory (`agent_model()`); source RAGAS and
  `judge_semantic` from it; wire ADK's native `JUDGED_METRICS` into the eval config/runner as an
  **opt-in judged tier**. The live `evaluate_pack`/`evaluate_plan` A2A path stays **deterministic and
  LLM-free**.
- **Why:** the only genuine "reuse ADK more" moves for an evaluator are (a) making its judge the one
  configured model (I8) and (b) using ADK's native judged harness instead of a bespoke one — not
  agent-ifying deterministic scoring, which would destroy reproducibility.
- **Consequence:** RAGAS stops silently defaulting to OpenAI; the judged tier is ADK-native and
  provider-backed; PQS/TPS stay reproducible. Realizes the "Open: Judged eval tier" item.
- **Status:** proposed; mirror into `DECISIONS.md` on adoption. Parallels KGA **D15** / TPD **D16**.

### Reconciliations
- **D1 (routers stay deterministic):** *upheld.* `EvaluatorAgent` is untouched.
- **D7 (state in the bank):** *upheld / N/A.* TEV is read-only; no interrogation state.
- **I1 (determinism):** *upheld and central.* The scorer's determinism is the product property; the
  judged tier is explicitly separate and opt-in.
- **I8 (model only via the provider):** *advanced.* The judge/embeddings now come from the provider
  instead of RAGAS's default or a test-injected client.

---

## 4. Invariants

- **Scorer determinism + read-only (product property, ≈ TPD's I3 in spirit):** the default
  `evaluate_pack`/`evaluate_plan` path makes **zero** LLM calls and is reproducible. The judged tier
  is a *separate*, opt-in, offline path — never merged into the default.
- **I8 (model via provider):** the judged tier's model is `agent_model()`; no OpenAI default, no
  ad-hoc client.
- **`eval` extra stays optional:** RAGAS remains behind the `eval` extra and skips cleanly when absent
  (unchanged); the ADK-native judged tier degrades to a skip when no `GOOGLE_CLOUD_PROJECT`/
  `VERTEX_PROJECT` (mirror `eval/runner.py::creds_available`).

---

## 5. ADK mechanics & gotchas

1. **ADK ships native judged metrics.** `hallucinations_v1`, `rubric_based_final_response_quality_v1`,
   `final_response_match_v2` are built-in LLM-judged evaluators in ADK's evaluation package — declaring
   them in the `EvalMetric` set (as `eval/config.py` already anticipates) is the ADK-native path; no
   RAGAS needed for those.
2. **The judge model is configured separately from the agent model.** ADK's judged metrics use a judge
   LLM (Vertex/GenAI-backed). Point it at the provider's Claude-on-Vertex so the judged tier and the
   agents share one model config (I8).
3. **RAGAS `llm=`/`embeddings=` injection.** `ragas_judge.judge` already accepts `llm`/`embeddings`;
   the fix is to *always* pass provider-sourced ones (wrap the provider's model in RAGAS's
   `LangchainLLMWrapper`/equivalent). Do not rely on the RAGAS default.
4. **Custom-metric functions are the reuse point, not `LlmAgent`.** For an evaluator, the ADK primitive
   to reuse is the **custom `EvalMetric` function** (`eval/adk_metrics.py`) — not `LlmAgent`. This is
   the structural reason the KGA/TPD conversion pattern does not transfer.

---

## 6. Milestones (V0–V4)

- **V0 — Judge factory.** Add `test_evaluation/eval/judge.py`: `build_ragas_llm()` /
  `build_ragas_embeddings()` / `build_semantic_judge()` sourced from `agent_model()` / the provider,
  with a clean skip when creds/extra are absent.
- **V1 — Route RAGAS through the provider.** Have the judged tests + any judged-tier entry pass the
  V0 judge into `ragas_judge.judge`, removing the silent OpenAI default.
- **V2 — Wire `judge_semantic`.** Make `judge_semantic` reachable via the V0 semantic judge in the
  judged tier only; add a report field. **Not** added to `evaluate_pack` default.
- **V3 — ADK-native judged metrics.** Add the `JUDGED_METRICS` to `eval/config.py` +
  `eval/runner.py` as an opt-in judged eval; map `SEMANTIC_RUBRICS` onto
  `rubric_based_final_response_quality_v1`. Gate on `creds_available()`.
- **V4 — Tests & docs.** Extend `tests/test_adk_eval.py` + `tests/eval/*` for the provider-sourced
  judge (mock model); assert the **default scorer still makes zero LLM calls**; record D17.

---

## 7. Verification gates

- **[verify @V1] No OpenAI default.** With the `eval` extra present, the judged tests use the
  provider-sourced judge; RAGAS is never called without an explicit `llm=`.
- **[verify @V2/V4] Determinism preserved.** `evaluate_pack`/`evaluate_plan` make **zero** model calls
  (call-count assertion) — the judged tier is separate and opt-in.
- **[verify @V3] ADK-native tier runs (creds only).** The `JUDGED_METRICS` eval executes under
  `AgentEvaluator` when `GOOGLE_CLOUD_PROJECT`/`VERTEX_PROJECT` is set, and skips otherwise.
- **[verify @V0] Offline default.** With no creds and no `eval` extra, the whole judged surface skips
  cleanly (no import error, no network).

---

## 8. Non-goals

- **Do NOT agent-ify the scoring engines.** `evaluate_pack`/`evaluate_plan` and every metric in
  `metrics/*` stay deterministic. Converting them to `LlmAgent`s would destroy PQS/TPS reproducibility
  — the opposite of what a scorer is for. **This is the whole reason TEV differs from KGA/TPD.**
- **Do NOT convert `EvaluatorAgent`** to an `LlmAgent`/coordinator (D1).
- **Do NOT add an LLM call to the live/default scoring path.** The judged tier is opt-in + offline.
- **Do NOT drop RAGAS** — it stays behind the `eval` extra as one judged option alongside the
  ADK-native metrics; V-work only changes *which model* it uses.

---

## 9. Test repoint

- `tests/eval/test_eval_judged.py`, `tests/eval/test_eval_tpd_judged.py` — pass the V0
  provider-sourced judge instead of relying on RAGAS defaults; keep the `ragas.available()` skip.
- `tests/test_adk_eval.py` — add the ADK-native judged-metric wiring (creds-gated) + the
  **zero-LLM-call** assertion on the default scorer.
- `tests/eval/test_metrics.py` — unchanged (regex rubrics + deterministic metrics).
