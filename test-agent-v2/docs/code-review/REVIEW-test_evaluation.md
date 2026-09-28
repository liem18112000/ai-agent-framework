# Code Review & Audit — `test_evaluation`

**Target:** `test-agent-v2/src/test_evaluation` (30 files · 1,276 LOC)
**Commit:** `618169c` · branch `feature/test-agent/v2-adk` · **Date:** 2026-09-11
**Method:** unified two-lens pass — `/code-review max` (correctness + security) and the **ponytail-review** lens (over-engineering / what to delete), run as two independent reviewers. Every load-bearing finding was re-derived against the actual code (`ops.py`, `engine.py`, `plan_engine.py`, `agent.py`, `metrics/rubrics.py`, `common/interrogate/present.py`) before being kept; refuted candidates are in the *Verified-not-a-bug* appendix so they don't get re-investigated. Observed test state: `uv run pytest -q tests/ -k eval` → **83 passed, 7 skipped** (the 7 are the RAGAS/judged tier — skipped offline without the `eval` extra + Vertex creds).

---

## Scorecard

| Lens | Result |
|---|---|
| **Correctness / Security** | 0 High · 3 Medium · 2 Low |
| **Over-engineering (ponytail)** | ~11 LOC safe-now · up to ~420 LOC if the parallel `eval/` layer + orphan metrics are dropped (a **product** decision) |
| **Overall** | Sound package: the metric math (precision/recall/F1, coverage, oracle, fault-class, weighted PQS/TPS with weights summing to 1.0) computes correctly with proper empty-set/zero-division guards, the live path is genuinely LLM-free and correctly offloads blocking bank I/O via `asyncio.to_thread`, and the OpenAI-fallback guard is a real security control. No crashes on the live path, no secret/PII leakage. The defects cluster in **two scoring seams that silently return a wrong score** — worth fixing before this is trusted as a quality gate. |

**Should be fixed before this is trusted as a gate:** **M1** (`evaluate_plan` scores the wrong context for non-`run-` ids), **M2** (`evaluate_pack` faithfulness false-zeros a well-grounded pack), and **M3** (Jira-key regex over-matches standard tokens → same false-zero). All three are *silent* — they produce a plausible-looking but wrong number, and offline tests mask them.

---

## ✅ Resolution (2026-09-12)

All 5 correctness findings + the 3 safe ponytail cuts were fixed in one pass. Full suite after: **460 passed, 14 skipped, 0 failed** (was 457 → **+3 regression tests**), ruff clean. The parallel `eval/` Plan-B layer and the history/topic/noise metrics were **deliberately kept** (test-backed nightly gates — a product decision, not a defect).

| # | Finding | Status | What changed |
|---|---|---|---|
| **M1** | `evaluate plan <ctx>` parses ctx as `"plan"` | **Fixed** | Root cause in the shared `common/interrogate/present.py`: the `<cmd> <id>` fallback now skips chained command nouns → returns the first non-command token. Fixes it for any 3-token command, all callers. Test: `test_extract_ctx_handles_three_token_plan_command`. |
| **M2** | `evaluate_pack` URL check vs URL-poor haystack | **Fixed** | `engine.py` now scores URLs against `pack.summary_text()` (mirrors `plan_engine`); `_pack_view` returns the pack. Test: `test_evaluate_pack_url_check_uses_pack_summary_not_titles`. |
| **M3** | `_JIRA_KEY` over-matches `ISO-20022`/`CVE-…` | **Fixed** | `cites_only_real_ids` only flags a key whose **project prefix** appears in the pack's real `jira:` ids — standards/CVE/RFC tokens are ignored. Test: extended `test_rubric_id_and_url_fabrication_guards`. |
| **L4** | `coverage.py` `KeyError` on id-less behaviour | **Fixed** | The `per` comprehension now carries the same `if "id" in b` guard as line 17. Test: `test_coverage_scores_tolerates_id_less_behaviour`. |
| **L5 / P-DF** | `trajectory=1.0` dead param | **Fixed (param dropped)** | Removed the never-passed `trajectory` kwarg from `evaluate_pack`/`evaluate_plan`; inlined `1.0` with a comment. **Blind-spot retained by design** — real trajectory is scored in the `adk eval` harness; renormalizing the live weights would change every existing score for no gain. |
| **P1** | `RetrievalScore.f1` never read | **Cut** | Removed the field + its computation (`models.py`, `node_overlap.py`). |
| **P2** | `EvalReport.tiers` never set/read | **Cut** | Removed (distinct from the used `expected_tiers`/`RunTrace.tiers`). |
| **P3** | `PlanEvalCase.behaviour_ids()` uncalled | **Cut** | Removed. |
| **P4** | descriptive golden-schema fields | **Kept (won't-cut)** | `shape`/`expected_*` mirror the golden-JSON contract and are filtered by `from_dict`; removing them buys 4 lines for a latent `AttributeError` footgun. They document the schema — kept deliberately. |
| **P5–P7 / `eval/` Plan B** | ~420 LOC test-only | **Kept (product decision)** | The ADK-native evaluator + history/topic/noise back real nightly regression gates; deleting working, tested code is a product call, not a review fix. Flagged for your decision. |

---

## Correctness / Security findings

### M1 — `evaluate_plan` scores the **wrong context** for any non-`run-` id · `ops.py:9-10` (+ `agent.py:20`, `common/interrogate/present.py:20`) · CONFIRMED
`extract_ctx(text)` delegates to `present.extract_ctx(text, ("evaluate","score","plan","pack"))`, whose final fallback is `<cmd> <id>` → `parts[1]`. The plan command is **three** tokens — `"evaluate plan <ctx>"` — so `parts = ["evaluate","plan","<ctx>"]` and it returns the literal word **`"plan"`**, not the context id. In `agent.py:20`, `ctx_id = extract_ctx(text) or ctx.session.id` — `"plan"` is truthy, so it **shadows** the correct `ctx.session.id` fallback.
- **Failure scenario:** a client gathers with a custom id (`gather_knowledge(context_id="LUZ-158390")` — the MCP param allows it), then `evaluate_plan("LUZ-158390")`. The agent computes `ctx_id="plan"` → `golden_plan_for("plan")=None`, `load_pack(bank,"plan")` → empty → returns a TPS scored on **nothing**, rendered `"Test-Plan Score for plan: …"`. No error.
- **Why it's only Medium:** the default pipeline reuses the gather-generated **`run-xxxx`** id, which the `\b(run-\w+)\b` branch (present.py:17) rescues *before* the buggy fallback — so the common flow is safe. It fires on any custom / non-`run-` id, and `evaluate_plan` **ignores** the correctly-passed `context_id` because it re-parses from text. `evaluate_pack` is unaffected (its command is the two-token `"evaluate <ctx>"`).
- **Test gap:** `test_agent_evaluates_plan_by_ctx` uses ctx `eval-LUZ-501` (→ `"plan"`) yet passes because it only asserts `"Test-Plan Score" in out`, never the id.
- **Fix:** the agent already *has* the right id — pass `ctx_id` into `evaluate_plan` and stop re-deriving it, or make `present.extract_ctx` skip a bare command-noun (`plan`/`pack`) when it is `parts[1]`. Assert the rendered context id in the test.

### M2 — `evaluate_pack` faithfulness false-zeros a grounded pack (URL check vs a URL-poor haystack) · `engine.py:20,37` · CONFIRMED (structural)
`_pack_view` builds `texts = [f"{n.title} {n.id}" for n in pack.notes]` (engine.py:20), then `no_invented_urls(understanding, " ".join(node_texts))` (engine.py:37). The haystack is **titles + node-ids**, which essentially never contain URLs (URLs live in note synopses / `LinkRecord.url`). So any real `http(s)://` the understanding legitimately copied from a note is judged *fabricated* → `rub_urls.passed=False` → `faithfulness = float(rub_ids.passed and rub_urls.passed) = 0.0` → PQS loses its **largest weight (0.30)** on a perfectly grounded pack.
- **Contrast (the tell):** `plan_engine.py:49` does the identical check **correctly** against `pack.summary_text()` (synopses + link URLs). `engine.py` is the odd one out.
- **Failure scenario:** a prod understanding restates a ticket and includes `https://axonivy.atlassian.net/browse/LUZ-501` (present in the pack) → not found in `"<title> jira:LUZ-501 …"` → "invented URL" → PQS −0.30 + a spurious finding in the report.
- **Test gap:** offline tests use the heuristic (no-LLM) understanding, which is URL-free, so the branch never triggers.
- **Fix:** score URLs against `pack.summary_text()` in `evaluate_pack` too (mirror `plan_engine`).

### M3 — `_JIRA_KEY` over-matches standard/CVE/RFC tokens → false "invented Jira id" → faithfulness=0 · `metrics/rubrics.py:9` · CONFIRMED (regex) / PLAUSIBLE (trigger)
`_JIRA_KEY = re.compile(r"\b[A-Z]{2,}-\d+\b")` also matches `ISO-20022`, `UTF-8`, `SHA-256`, `CVE-2021`, `RFC-2616`. `cites_only_real_ids` treats any such token in the understanding as a Jira key; none are in the pack's `jira:` ids → `invented` non-empty → `faithfulness=0` (−0.30 PQS), compounding M2.
- **Failure scenario:** a QR-bill / payment understanding (this system's actual billing domain) says "conforms to **ISO-20022**" → flagged as a fabricated Jira key → PQS tanked. PLAUSIBLE because it needs the hyphenated form (`ISO-20022`, not `ISO 20022`).
- **Fix:** anchor the key to the project-key shape actually used (e.g. require a known project prefix, or exclude a small stoplist of standards families), or validate against the set of prefixes present in the pack.

### L4 — `coverage.py:19` `KeyError` on an id-less golden behaviour → 500 instead of a degraded score · PLAUSIBLE (latent)
Line 17 guards `beh = {b["id"] for b in behaviours if "id" in b}`, but line 19 `per = {b["id"]: … for b in behaviours}` indexes `b["id"]` **unconditionally**. `PlanEvalCase.behaviour_ids()`/`from_dict` tolerate an id-less entry, so a malformed golden plan raises `KeyError`, which propagates out of `evaluate_plan` as a 500 through the MCP tool rather than degrading. Not reachable with the current three golden plans (all have `id`) or the generated fallback — a latent robustness gap on hand-authored golden input.
- **Fix:** reuse the same `if "id" in b` guard in the `per` comprehension.

### L5 — `trajectory` is hardcoded `1.0` on the live path → constant unearned **+0.10** in every PQS/TPS · `engine.py:24` / `plan_engine.py:22` · CONFIRMED (by design, but a scoring blind spot)
Both engines take `trajectory: float = 1.0` and the live agent path never passes anything else, so the trajectory component (0.10 weight in both `WEIGHTS`/`TPS_WEIGHTS`) is **always full credit** regardless of the agent's real tool sequence. Actual trajectory is only measured in the separate ADK-native `adk eval` harness. Relative ranking survives (it's a constant), but a genuinely bad trajectory is invisible to the live gate, and the composite advertises a component it never evaluates. *(Both review lenses flagged this — see the ponytail note P-DF.)*
- **Fix (pick one):** wire the real ADK trajectory score into the live path, **or** drop the parameter and renormalize the live weights so PQS/TPS don't include an un-measured 0.10 (and document that live scores exclude trajectory).

---

## Over-engineering (ponytail) — what to delete

### Safe now (dead code · no behaviour change · no test breaks) — net ≈ −11 LOC
| # | Location | Cut | Replaces / note |
|---|---|---|---|
| P1 | `models.py:38` + `metrics/node_overlap.py:14` | `RetrievalScore.f1` field + its `2*p*r/(p+r)` computation | `.f1` is never read in `src` or `tests` — delete field + line + arg (~3 LOC) |
| P2 | `models.py:144` | `EvalReport.tiers` field | never set by `engine.py`, never read (~1 LOC) |
| P3 | `models.py:170-171` | `PlanEvalCase.behaviour_ids()` | zero call sites (~3 LOC) |
| P4 | `models.py:15,16,151,155` | unused descriptive fields `EvalCase.shape`, `EvalCase.expected_trajectory`, `PlanEvalCase.shape`, `PlanEvalCase.expected_rounds` | only appear as golden-JSON annotations, which `from_dict` filters — safe to drop (~4 LOC). *(Keep `PlanEvalCase.expected_trajectory` — it IS read by `tpd_deterministic`.)* |

### Dead flexibility — needs a one-line decision
| # | Location | Observation |
|---|---|---|
| P-DF | `engine.py:25`, `plan_engine.py:23` | `trajectory=1.0` (all 11 call sites omit it) and `detail=False` passthrough (tests call `placeholder_scan(detail=True)` directly, never through `evaluate_plan`) are **dead params today**. Resolve together with **L5**: either wire them or inline the constants. |

### Feature reduction (test-only today — a product call, not a silent cut)
| # | Location | Observation |
|---|---|---|
| P5 | `metrics/history.py` (33 LOC) + `HistoryRecord` (`models.py:114-127`) | PQS trend-history JSONL with **no runtime/CI caller** — the only consumer is `test_history_round_trip`. Clearest YAGNI (~47 src LOC). Keep the 1-line `regressed()` if the nightly wants it. |
| P6 | `metrics/topic.py` (16 LOC) | `adherence`/`adherence_curve` — nothing feeds it `round_terms`; only its own test calls it. `adherence_curve` is a 1-line wrapper over `adherence`. |
| P7 | `metrics/noise.py` (15 LOC) + `NoiseScore` | `drift_score` memory-bleed metric, not wired to any engine; backs only the nightly `test_noise_sensitivity_*`. Cut only if you don't want that nightly regression check. |

### The strategic one (flag, don't cut)
- **The entire `eval/` subdir** (`config`, `adk_metrics`, `evalset`, `runner`, `judge`, `judged`) + `metrics/ragas_judge.py` — **~370 LOC of a second, parallel evaluation implementation** (ADK-native "Plan B" that re-expresses the deterministic engine as `adk eval` custom metrics + a RAGAS judged tier). Nothing on the live A2A path imports `test_evaluation.eval`; its only consumers are its own tests. This is a **deliberate, heavily test-locked design decision** (the ADK-transform Plan B) — a product conversation about whether the parallel evaluator earns its LOC, **not** a review delete.

**KEEP (intended design — do not re-flag):** the live `metrics/*` scorers (all wired into the engines *and* shape-locked by `test_metrics`/`test_eval_tpd_metrics`); `metrics/trajectory.py` (nightly-fed, 4 modes asserted); `metrics/gherkin_lint.py` (live nightly gate even though `PlanReport.gherkin` stays `None`); the `from_dict` unknown-key filtering (makes P4 safe); and — critically — **`eval/judge.py`'s `llm=None` refusal + `ragas_judge`'s `ValueError`** that block RAGAS's silent OpenAI fallback (a security/correctness guard, test-locked by `test_ragas_judge_refuses_openai_default` — never simplify away). The **one-file-per-metric split** is fragmentation rather than a plugin seam (engines import specific functions; no registry/iteration), but every file is live or test-locked, so collapsing wins only ~4 header lines each — not worth the churn beyond the orphan trio P5–P7.

---

## Verified-not-a-bug (refuted — do not re-investigate)
- **`node_overlap.py:13` `recall=1.0` when `relevant` empty** — documented default for the no-golden path (precision still 0.0); matches the known "recall=1.0 + precision=0.0 = complete-but-noisy" behaviour.
- **`placeholders.py:22` always `passed=True` when `detail=False`** — the live default; `placeholders` isn't a `TPS_WEIGHTS` component, so it can't corrupt the score.
- **`ragas_judge.py:40` `float(row[k])` NaN** — RAGAS NaN is never folded into the live PQS (live faithfulness is the deterministic rubrics); only the nightly reads it, where `nan >= 0.5` fails *loudly*, not silently.
- **`agent.py:21` `build_bank()` sync in the async handler** — constructs only the (lazy) store client; real I/O is inside `to_thread`. Same pattern as KGA/TPD. Negligible.
- **`entities.py:8` haystack = titles+ids only** — over-strict in theory, but golden `key_entities` are calibrated to titles and all tests pass; not a current-data defect. *(Unlike M2, the entities haystack is by-design keyed to titles; the URL check is not.)*
- **`plan_engine.py:49` `summary_text()` 6000-char truncation** — a URL past 6000 chars could false-positive, but pack URLs appear early (per-note, near the top); unproven.
- **`oracle.py:15` `_ENUM` marks all-caps English words "strong"** — an explicit deterministic proxy for mutation strength; acceptable heuristic, not wrong math.

---

## One-line summary
A well-factored, correctly-async scorer whose only real risks are **silent wrong scores** in two seams: the shared `extract_ctx` heuristic mis-parses the 3-token `evaluate plan <ctx>` command (M1), and the `evaluate_pack` faithfulness rubric false-zeros grounded packs via a URL-poor haystack (M2) and an over-broad Jira-key regex (M3). Fix those three; treat the parallel `eval/` Plan-B layer and the three test-only metrics (history/topic/noise) as a product decision on ~420 LOC, not a code-review delete.
