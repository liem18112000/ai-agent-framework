# Prompt quality — why the assured score can't be trusted yet, and what to do

**Status:** research + plan · **Date:** 2026-09-17 · **Repo:** `test-agent-v2`

Three parallel research streams (LLM-judge reliability · prompt-optimization tooling · an audit of our
12 prompt bodies against Anthropic's own `prompt-audit` method) converged on one conclusion:

> **The judge is the bottleneck.** It is unstable by nature, primed by its own wording to score low,
> and runs with thinking disabled. Until it is stabilized, a score delta is not evidence — which means
> every "the fix worked, the score went up" claim in this project, including mine, is weak.

---

## 1. The instability is expected, not a defect

"Rating Roulette" (arXiv 2510.27106) measured intra-rater reliability by re-running judges on
**identical** inputs: Krippendorff's α = **0.27–0.56** (MT-Bench), **0.33–0.79** (SummaC). An LLM judge
disagrees with *itself* about as much as two mediocre human annotators do. Temperature 0 does not fix
it (kernel/batching nondeterminism) and hurts quality.

Our `run-e778a050` sequence — **0.08 / 0.28 / 0.08 / 0.34** — sits at the bad end of that documented
regime. So:

- The `max_tokens` truncation fix was real, but the **strong** evidence is the log showing batches
  stopped degrading to the heuristic — *not* the 0.28 → 0.34 move.
- P7's A/B comparison is attributable but **not conclusive**. Attribution ≠ significance.

### What the score is currently measuring

| Contributor | Effect |
|---|---|
| Judge sampling noise | Large — the dominant term today |
| Judge register ("STRICT… punish invention") | Systematic downward bias |
| `thinking: disabled` on the judge call | Unknown, plausibly negative on a judgment-heavy task |
| Actual suite quality | The thing we want — currently the smallest signal |

---

## 2. Fixes, ranked by impact ÷ effort

From the reliability research, cross-checked against the tooling research (which independently picked
the same #1):

1. **Sample the judge k=3–5 and aggregate (median).** Judge calls take seconds against a ~10-minute
   pipeline, so this cuts judge variance ~√k with **no extra pipeline run**. Majority/median beat
   single-run in every configuration tested.
2. **One judge call per dimension.** Anthropic's agent-eval guidance: grade each dimension with an
   isolated judge rather than one call for all. Our 7 dimensions share **one sampling event**, which is
   exactly why the aggregate swings as a block (the 0.08-vs-0.3 two-mode pattern).
3. **Replace the 7 floats with binary per-criterion checklists; compute ratios in code.** Ternary →
   binary raised human agreement ~20 points in ResearchRubrics. `ac_coverage = passed/total` becomes
   arithmetic instead of a guess. Keep the 7 *dimensions*; drop the float.
4. **Anchor the rubric with 2–3 scored reference examples.** Criteria quality — not CoT, not scale — is
   the dominant reliability driver.
5. **Allow `unknown` per criterion** instead of forcing a number.

### How to measure the judge itself

- Use **chance-corrected** agreement (Cohen's κ / Krippendorff's α). 85% raw match ≈ κ 0.48.
- Report **test-retest** (≥3 repeats of one input) *separately* from accuracy. Good judges exceed 0.94
  test-retest; ours is far below — **stability before accuracy**.
- There is **no published κ/α threshold for "trustworthy."** The agreement-metrics literature declines
  to give one; α ≥ 0.667 is borrowed from content analysis and is not validated for judges.

### Contested — do not overstate

CoT-before-scoring is contested (minimal gain once criteria are clear). The ~20-point binary gain is
one benchmark in another domain. Pairwise judging beats pointwise for *ranking models* but does not fit
us — we have no second suite to compare against. Position bias does not apply (we are pointwise);
verbosity bias measured < 0.011 across 21 judges.

---

## 3. Tooling: adopt nothing new

| Tool | State (checked 2026-09-17) | Verdict |
|---|---|---|
| DSPy (MIPROv2 / GEPA) | active, 38k★, MIT | **premature** — see below |
| TextGrad / promptim / OPRO / APE | dormant or dead | avoid |
| promptfoo | active, MIT — acquired by OpenAI 2026-03, stays OSS | CI contract assertions only |
| Langfuse | active, MIT — acquired by ClickHouse 2026-01, self-host unchanged | only for a non-engineer prompt UI |
| Humanloop | **sunset 2025-09-08**, data deleted | do not adopt |

**DSPy is premature for three independent reasons, any one fatal:** MIPROv2 wants 200+ examples (we
have a handful of runs); GEPA's cheapest preset is ~290 metric calls per prompt — ~3000 for twelve, i.e.
days-to-weeks at 10 min/run; and DSPy wants to **own prompt construction** via Signatures/Modules, so
adopting it means rewriting the agent rather than optimizing text in our rows.

**Steal GEPA's idea manually instead:** feed the judge's textual critique of the 5 worst runs to a
strong model, have it rewrite **one** prompt, ship as a new version, compare paired. Same reflective
loop, zero dependencies.

We already own what the platforms sell — versioned prompts, per-run pinned attribution, a metric. **The
bottleneck is run count, not tooling.**

### The number that matters

**~15–20 paired tickets per arm, resolving only Δ ≥ 0.10.** Paired design, `n = 7.85·(σ_d/Δ)²`
(α=.05, 80% power), σ_d ≈ 0.15 → Δ=0.10 gives n≈18; Δ=0.05 gives n≈71 (~24h of runs per arm — don't).
Run the same tickets through both arms; unpaired doubles n for nothing. **If the observed delta is under
~0.05, report "unresolved", not "no change".**

> σ_d = 0.15 is a **prior**, not our measurement. Measure it from our own runs before trusting the n.

---

## 4. Audit of our 12 prompts — what is actually wrong

The audit was deliberately conservative and **kept** most of the caps emphasis, because its provenance
is recent and earned: the `tpd.scope_classify` shouting traces to `afbc069` (2026-09-17) fixing a
demonstrated 35/41 sibling-ticket failure **on this model**. Prohibitions against a current, reproduced
failure are keep-list material.

The genuine defects are narrow:

| # | Key | Problem | Confidence |
|---|---|---|---|
| 1 | `tpd.scenarios` | **Self-contradiction.** "there is NO cap; aim to cover 100%" (pre-batching fossil) renders directly above `$focus` saying "GENERATE ONLY for these pack unit ids … NONE for any id not listed". Two opposite ceilings in one prompt. | High |
| 2 | `kga.hypothesize` | **Bans our own domain vocabulary.** "AVOID generic words like: document, system, data, … mapping" — while we crawl **luz-docs, a document-management product**. It suppresses the best search terms available. | High |
| 3 | `kga.hypothesize` | Near-duplicate sentence: "the MOST distinctive, specific search terms" restated verbatim on the next line. | High |
| 4 | `tpd.judge_scenarios` | **Register bias.** "STRICT … punish invention" primes a low scorer, and `faithfulness` already encodes the rule *with its reason*. | Medium |
| 5 | `engine.questions` | Emphatic "ONLY genuine judgement calls" was written to stop question spam; our **observed** failure is the opposite — rounds returning zero questions. | Medium |
| 6 | `tpd.scenarios` | Third statement of one rule (`$scope_block` and `PACK_GROUNDING` already say it). | Medium |

Plus a config finding: **`vertex.py:54` hardcodes `thinking: {"type": "disabled"}` globally**, including
on the judge and scope classifier — the two most judgment-heavy calls in the system.

### ⚠️ Do not "de-shout" these — they are code contracts

`TEST SCENARIOS`, `TEST DATA`, `STEP-BY-STEP`, `QA CRITIC` look like textbook pressure language and are
**matched by test code**: `tests/tpd_fakes.py` routes the offline fake model on those substrings, and
`test_plan_assured.py` asserts the judge avoids the generator markers. Reword them and the suite breaks
in a way that looks like a generator bug. (This is exactly the audit method's "check out-of-band
dependencies" step.)

### Already well-calibrated — no change needed

`engine.understanding`, `tpd.brief`, and `kga.leads`. `kga.leads` is what `kga.hypothesize` should look
like: states its goal, no ban list.

---

## 5. Plan

| Step | Scope | Status |
|---|---|---|
| A | Judge stabilization: k=3 median + register fix | see §6 |
| B | The 5 prompt edits from §4 | see §6 |
| C | Binary rubric rewrite (§2 item 3) | **deferred** — largest change; touches `JudgeVerdict`, the loop, and tests |
| D | Per-dimension judge calls (§2 item 2) | **deferred** — 7× the judge calls; evaluate after A |
| E | Paired-bootstrap significance query over Postgres | not started |

### ⚠️ Operational note for any prompt edit

The database now serves **12/12 prompts** (seeded 2026-09-17). Editing a body in `templates.py` and
redeploying **does not change what runs** — the seeded DB row still serves the old text. After an image
edit you must either `prompt_publish` the new body or run `prompt_seed force=true` to bring rows back in
line with the image. This is the cost of the store being authoritative, and it is easy to forget.

---

## 6. Sources

Judge reliability: arXiv [2510.27106](https://arxiv.org/html/2510.27106v1) (Rating Roulette),
[2511.07685](https://arxiv.org/pdf/2511.07685) (ResearchRubrics), [2506.13639](https://arxiv.org/abs/2506.13639)
(judge design choices), [2606.19544](https://arxiv.org/html/2606.19544v1) (agreement metrics);
[Anthropic — demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents);
[hamel.dev evals-faq](https://hamel.dev/blog/posts/evals-faq/why-do-you-recommend-binary-passfail-evaluations-instead-of-1-5-ratings-likert-scales.html).
Tooling: [DSPy](https://github.com/stanfordnlp/dspy), [GEPA](https://github.com/gepa-ai/gepa),
[promptfoo](https://github.com/promptfoo/promptfoo), [Langfuse](https://github.com/langfuse/langfuse),
[Humanloop sunset](https://humanloop.com/docs/guides/migrating-from-humanloop).
Audit method: `claude-api` skill → `shared/prompt-audit.md`.
