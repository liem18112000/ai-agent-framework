# How JEV works — a deep dive

*Explainer · 2026-09-21 · companion to [`RESEARCH-typesafe-jev.md`](RESEARCH-typesafe-jev.md) (what Jev is + Jev vs LLM) and [`RESEARCH-jev-in-test-agent-v2.md`](RESEARCH-jev-in-test-agent-v2.md) (how we'd apply it).*

---

## What this is

The two research notes cover *what* Jev is and *where* we'd use it. This doc is the mechanism: **how a single call is shaped, why it's fast, what each of the three question primitives actually returns, what "calibrated" means, and how you turn a verdict into an action.** One diagram per concept, each followed by the prose that explains it.

**Jev (JEV)** is a **System-1 decision model** — not an LLM. It does not generate prose token-by-token; it takes unstructured *state* plus a set of *typed questions* and returns **typed, calibrated answers in one parallel pass**. It classifies, scores, and routes. It does not reason or write. Read this doc as "the engine behind the routing/scoring/yes-no calls," not "a smaller chatbot."

> **Honesty note (applies to the whole doc):** every latency / cost / accuracy magnitude below is a **vendor claim** (TypeSafe's own workflow evals), repeated as such. Jev's internal architecture is **not publicly documented**, so the two diagrams that depict "how it computes" are labelled **conceptual / illustrative** — they show the *mechanism being contrasted*, not a claimed implementation.

---

## 1. The shape of a call — one state, N typed questions in; one typed verdict per question out

![JEV request and response anatomy: one shared state plus a list of N typed questions in, a typed verdict with a probability distribution and confidence per question out](jev-hiw-request-anatomy.png)

Every Jev call is a single JSON object: **`{ state, questions }`**.

- **`state`** is the unstructured context — logs, a JSON blob, free text. It is shared by *every* question in the request; you send it once.
- **`questions`** is a **list (map)** of *N* typed questions. Each one declares its type up front — `Choice`, `Score`, or `Noul` (sections 3–5). Because the type is fixed before the call, the **shape of the reply is known in advance**: there is nothing to guess at parse time.

The response mirrors the request key-for-key. For **each** question you get back a small typed record: the **value** (the chosen option / the score / the probability), the **full probability distribution** behind it, and a **calibrated confidence**. In the example, `route` comes back as `"infra"` with the per-option spread `{infra:.78, auth:.14, billing:.08}` and confidence `0.78`; `quality` as a continuous `0.31`; `urgent` as a bare `noul:0.93`.

The payoff is in that last column of the diagram: your code **branches, sorts, and routes directly on typed fields**. There is no free text to parse, no schema to validate, no repair-and-retry loop when the model emits an out-of-schema string. Compared with an LLM — where you prompt, get text, parse it, validate it against a schema, and retry on failure — the "structured decision" is the *native* output here, not something you reconstruct afterwards.

Two properties set up the rest of the doc: the questions are answered **together in one pass** (section 2), and the confidence is **calibrated** (section 6) — which is what makes it safe to gate on (section 7).

---

## 2. One parallel pass vs token-by-token — why latency stays flat as N grows

![Conceptual contrast: JEV answers all N questions in one parallel pass so latency stays flat, while an LLM decodes token-by-token and re-runs per question so latency grows](jev-hiw-parallel-vs-autoregressive.png)

> **This diagram is conceptual / illustrative.** Jev's internals are not published; the point is the *class* of computation, not a claimed circuit.

An **LLM is autoregressive**: it produces one token, feeds it back in, produces the next, and so on. A structured answer is a sequence of tokens, so the cost scales with how much it has to emit — and if you have several independent questions, you typically **re-run the whole decode per question** (or stuff them into one prompt and still pay for the long generation). Latency therefore **grows** with the number of questions.

Jev is described as **non-autoregressive**: a request's questions are **evaluated in parallel in a single pass**. It is not emitting a token stream; it is producing typed verdicts. So adding a fourth, fifth, tenth question to the list barely moves the wall-clock — the little chart on the right sketches the intuition: a **flat** line for Jev, a **rising** line for the LLM (illustrative, not to scale).

This is the concrete reason for the headline numbers (**vendor claims**): **~70–500 ms** per Jev call versus **~3–329 s** for an LLM on comparable structured tasks, and **`$0.042 / M` input tokens with output free** versus roughly **`$0.20–10 / M` plus paid output**. The "output free" part falls straight out of the mechanism: there is no long token stream to bill for. When you have many small decisions over the same state, batching them into one Jev request is close to free per extra question — which is exactly the workload agents, guardrails, and eval loops generate.

---

## 3. Choice — pick 1 of ≤255 options, with a probability for each

![The Choice primitive: input options up to 255, a probability distribution over the options, and the argmax pick plus its confidence, worked through a ticket-routing example](jev-hiw-choice.png)

**Choice** is classification / routing: you give a fixed set of up to **255** options, and Jev returns a **probability for every option** (they sum to ≈ 1). The verdict is the **argmax** — the highest-probability option — together with its **calibrated confidence**.

The worked example routes an incident ticket whose state is *"DB connection pool exhausted — 500s across services."* The distribution puts `infra` at `.78`, `auth` at `.14`, `billing` at `.06`, `other` at `.02`. The pick is `infra`, confidence `0.78`.

Why return the whole distribution and not just the winner? Because the runner-up carries information. `auth .14` tells you the second-most-likely bucket; a distribution like `{infra:.40, auth:.38, …}` is a near-tie you'd treat very differently from a `.90/.05` landslide even though both have the same argmax. And because the confidence is calibrated (section 6), a low-confidence route can be **held for a human** instead of acted on blindly (section 7). This is the primitive behind ticket routing, relevance/label classification, and static-vs-fast model routing.

---

## 4. Score — a continuous score on an ordered rubric

![The Score primitive: an ordered rubric low less-than med less-than high maps to a continuous score plus level probabilities and confidence, worked through a test-suite-quality 0 to 1 example](jev-hiw-score.png)

**Score** is for rating on an **ordered** rubric — levels that have a *direction*, like `low < med < high`. Jev returns a **continuous score** (here on `0.0 .. 1.0`), the **probability mass across the ordered levels**, and a **calibrated confidence**.

The example rates a generated test suite's quality. The score lands at **0.73** — just inside the `high` band — with level probabilities `{low:.05, med:.22, high:.73}` and confidence `0.90`.

The distinction from Choice is the whole point of having a separate primitive: **use Score when the levels are ordered and you want a number, use Choice when the options are unordered categories.** "Billing vs auth vs infra" has no ordering — that's Choice. "low vs med vs high" is a ladder, and you often want the continuous position on that ladder (0.73), not just which rung — that's Score. Because the score is continuous *and* the confidence is calibrated, a fixed **accept-threshold on the score** ("ship the suite if quality ≥ 0.7") is meaningful. In our pipeline this is the natural fit for the assured-generation judge and the RAGAS-style judged tiers, where today an LLM is sampled several times and the median compared to a threshold — one calibrated Score removes the sampling variance hack (see the application note).

---

## 5. Noul — one calibrated P(true), not a hallucinated boolean

![The Noul primitive: a statement maps to a single calibrated probability of truth between 0 and 1, and a user-chosen threshold turns that probability into a yes or no](jev-hiw-noul.png)

**Noul** answers a yes/no question — but it does **not** hand you a boolean. It returns a **single calibrated probability that the statement is true**, in `0..1`. In the example, the statement *"This needs attention now"* over a state of *"deploy failed 2x; customers seeing 500s"* comes back as **`P(true) = 0.93`**.

### What "Noul" actually is

"Noul" is simply **TypeSafe's name for JEV's third question primitive** — the two others being `Choice` and `Score`. It is a coined product term (the public docs don't spell out an etymology, so don't read meaning into the letters); what matters is the *kind of thing* it denotes:

- **A probabilistic boolean.** A Noul question is one binary *proposition* — a statement that is either true or false — and the answer is the **probability that it's true**, not the truth value itself. Think of it as `Noul(statement) ≈ P(statement is true | state)`: you supply the statement, JEV supplies the probability, you supply the threshold. It's the Bernoulli (`0..1`) cousin of `Choice` (a distribution over discrete options) and `Score` (a magnitude on an ordered scale).
- **One number, and that number *is* the confidence.** Unlike `Choice`/`Score`, a Noul verdict has **no separate `confidence` field** — the response is just `{ "noul": 0.93 }`. For a binary truth claim the probability already carries the certainty: a value near `0.5` means "genuinely unsure", and distance from `0.5` toward `0` or `1` *is* how confident the model is. (Because it's calibrated — §6 — a `0.93` really does mean right ~93% of the time.)
- **When to reach for it.** Use `Noul` when the decision is a **single true/false proposition** and you want to keep the uncertainty and own the cut-off — guardrails, "is this risky/urgent/complete?" checks, semantic yes/no judges. Reach for `Choice` instead when there are three-plus mutually-exclusive options, and for `Score` when the answer is an ordered magnitude rather than a truth claim.

The **threshold is yours**, not the model's. You draw the line — say `0.80` — and everything at or above it is TRUE, everything below is FALSE. `0.93 ≥ 0.80`, so this one fires: act on it.

This is the difference the diagram argues on the left: an **LLM emits `true` / `false`** (or a made-up "confident" boolean), and you *cannot tell a 0.51 call from a 0.99 one* — the uncertainty is thrown away before you see it. Noul returns the probability, so **you own the risk tolerance** per call site (a guardrail might gate at 0.99; a cheap pre-filter at 0.5), and — crucially — the number is **calibrated**, which is what makes that threshold trustworthy. That is the next section. Noul is the primitive behind the semantic yes/no judges and the "enough info, stop asking?" interrogation gates in our system.

---

## 6. Calibration — what "calibrated confidence" actually means

![A reliability diagram contrasting a calibrated model whose curve hugs the diagonal with an overconfident LLM whose curve sits below it, illustrating why a calibrated confidence makes a threshold meaningful](jev-hiw-calibration.png)

> **The reliability curves here are illustrative** — a mental model, not measured numbers.

Every primitive returns a *confidence*, and gating on it is the whole automation story. But a confidence number is only useful if it **means something**. That's what a **reliability diagram** shows: plot the model's **predicted confidence** on the x-axis against the **observed accuracy** on the y-axis. If, across all the calls where it said "0.8," it turns out right about 80% of the time, the point sits **on the diagonal `y = x`** — that is *perfect calibration*.

A **calibrated** model's curve hugs the diagonal (the green line): **"when it says 0.8, it's right ~80% of the time."** An **LLM's self-reported confidence** typically does **not** — the purple curve sits below the diagonal (overconfident): it can say `0.95` and be right ~70%. Same stated number, very different reality.

Why this matters for everything above: **calibration is what makes the threshold real.** If you gate at `0.80` on a calibrated model, you genuinely keep the "≥80%-correct" bucket and know your error rate on the fast path. Put the same `0.80` gate on an uncalibrated self-report and the number doesn't map to accuracy — the gate is a guess. TypeSafe's claim that Jev is calibrated is *the* enabling property for the cascade in section 7. Standing caveat: calibration is **per-model and vendor-claimed** — re-benchmark it on your own golden sets, and re-check whenever the model updates, before you trust a threshold.

---

## 7. Gating + the JEV→LLM cascade — act, escalate, or hand to a human

![The gating and cascade flow: a JEV verdict is compared to a threshold, high confidence acts autonomously, the mid or low confidence tail escalates to an LLM or a human](jev-hiw-gating-cascade.png)

Sections 1–6 produce a **typed verdict + a calibrated confidence.** This section turns that into an action. A single threshold splits the confidence into bands:

- **HIGH confidence → act autonomously.** The fast path — the majority of calls resolve here at **~70–500 ms** and **`$0.042/M` in, output free** (**vendor claims**).
- **MID confidence → escalate to the LLM (System-2).** This is the **cascade**: Jev fronts the LLM, and only the *hard* cases pay for LLM reasoning. The LLM's reasoned verdict then acts or holds.
- **LOW confidence → hand to a human.** Hold the risky action; don't let either model guess.

The reason to cascade rather than replace is honest about Jev's limits: its **raw accuracy is reportedly below a frontier LLM judge** on at least one shared benchmark. So you don't drop the LLM — you **front** it. Jev handles the easy majority; the LLM judges the low-confidence tail. The economics (**vendor claim**): roughly **~90%** of calls resolved cheaply by Jev, **~10%** escalated. And because the fallback path is exactly today's LLM behaviour, the change is **strictly additive** — worst case, you're back to what you already run.

This is precisely the calibrated-confidence philosophy from section 6 applied operationally, and it is the shape we'd adopt in test-agent-v2: a `DecisionProvider` port beside the existing `ModelProvider`, Jev first, LLM on the tail, flag-gated and default-off. The call sites and rollout are in [`RESEARCH-jev-in-test-agent-v2.md`](RESEARCH-jev-in-test-agent-v2.md).

---

## Sources

Facts and figures in this doc are drawn from **[`RESEARCH-typesafe-jev.md`](RESEARCH-typesafe-jev.md)** (which cites TypeSafe's launch + docs, LangChain's Jev write-ups, Arize's LLM-judge comparison, and independent explainers). See that note for the primary links and the Jev-vs-LLM table.

> **All performance, cost, and accuracy magnitudes in this document are vendor claims** (TypeSafe's own workflow evals, not independently verified ground truth), and the "how it computes" diagrams (sections 2 and 6) are **conceptual / illustrative, not a claimed architecture.** Treat every number as directional and benchmark on your own data before trusting a threshold.
