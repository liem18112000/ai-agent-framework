# TypeSafe AI — Jev (JEV): What it is, and how it differs from an LLM

*Research note · 2026-09-21 · sources at the bottom. Vendor performance numbers are TypeSafe's own claims — flagged as such and not independently verified.*

---

## TL;DR

**Jev** is TypeSafe AI's first **"System One" model** — a decision model, **not an LLM**. Instead of generating text token-by-token, it takes unstructured *state* plus a set of *typed questions* and returns **typed, calibrated answers in a single parallel pass**. It classifies / scores / routes; it does **not** reason or write prose. Vendor claims: ~70–500 ms latency, `$0.042 / M` input tokens (output free), and *mathematically* no type errors / hallucinated fields. Independent caveat: its **raw accuracy is reportedly below a frontier LLM judge** on at least one shared benchmark, so it's a *fast primitive for the easy 90%*, with an LLM kept for the hard tail.

![JEV vs LLM — System-1 single parallel pass vs System-2 autoregressive decode](jev-concept.png)

---

## The 5 W's

### What
A **System One (System‑1) model**: fast, structured decisions software consumes directly. Output is a typed value + a probability distribution + a **calibrated confidence**, so code can branch/sort/route on it with no text parsing. Every request is a *state* + one or more *typed questions*, and **all questions are evaluated in parallel** — adding questions barely moves latency. Three question primitives:

![JEV's three primitives (Choice / Score / Noul) and confidence gating](jev-question-types.png)

| Primitive | Question | Returns |
|-----------|----------|---------|
| **Choice** | pick 1 of up to 255 options | chosen option + probability per option + confidence |
| **Score** | rate on an ordered rubric | continuous score + level probabilities + confidence |
| **Noul** | is this statement true? | a single calibrated probability 0–1 |

### Why
TypeSafe's thesis: most "agent" pipelines force an **LLM to do routing / classification / structured decisions** — paying generative cost + latency for tasks that need *no creativity*. Founder Diogo Almeida (ex‑OpenAI, instruction‑following work behind ChatGPT) frames it as *"models are superhuman at chat, so where is the automation?"* Jev extracts the decision step into a dedicated primitive that is cheap, fast, type‑safe, and **calibrated** (higher confidence ⇒ genuinely higher accuracy), which chat models are not.

### When
Launched **September 2026**, early‑access / waitlist. Use it for **high‑volume, repeated decisions over shared state where the answer set is known up front** — routing, classification, scoring, yes/no gates, guardrails, evaluation — especially inside real‑time loops (agents, games, robots, simulations). **Don't** use it where you need generation, explanation, or open‑ended reasoning — that stays an LLM.

### Where
Accessed via API/SDK (incl. a `langchain_typesafe` integration exposing `TypeSafeClassifier`, `Noul`, and experimental `AutoModeMiddleware` / `ModelRouterMiddleware`). Reported constraints: **32K context**, **text + JSON only (no images)**, and **not on Bedrock / OpenRouter** yet — needs custom integration.

### How
Send `{ state, questions }` → get typed answers + confidence back in one pass. Sketch (LangChain integration):

```python
from langchain_typesafe import Noul, TypeSafeClassifier
clf = TypeSafeClassifier()
r = clf.invoke({
    "state": "deploy failed twice; customers seeing 500s...",
    "questions": {"urgent": Noul(instructions="Does this need attention now?")},
})
# r["urgent"] -> calibrated probability; branch on a threshold you set
```
The developer sets a **confidence threshold**: high → act autonomously; mid → follow‑up / escalate to an LLM; low → hold for a human.

---

## Jev vs LLM

| Dimension | **Jev (System‑1)** | **LLM (System‑2)** |
|-----------|--------------------|--------------------|
| Computation | non‑autoregressive, **single parallel pass** | autoregressive, token‑by‑token |
| Output | **typed** value + probabilities + confidence | free text (then parse + validate + retry) |
| Confidence | **calibrated** (built‑in) | self‑reported, often over/under‑confident |
| Failure modes | *0%* type errors / no hallucinated fields (vendor claim) | can hallucinate, emit malformed / out‑of‑schema data |
| Latency (vendor) | ~70–500 ms | ~3–329 s on comparable structured tasks |
| Cost (vendor) | `$0.042 / M` in, output free | ~`$0.20–10 / M` + paid output |
| Reasoning / generation | **none** — decisions only | yes — its whole point |
| Raw accuracy | reportedly **below** a top LLM judge on some tasks | frontier |
| Maturity | early‑access, 32K ctx, text/JSON only | mature, broad ecosystem |

**How to read this:** Jev is not "a better LLM" — it's a *different tool*. It wins decisively on the **narrow, repeated, schema‑known decision** where an LLM is overkill (latency, cost, and the parse/validate tax). The LLM still owns generation, explanation, and the ambiguous cases. The practical pattern is a **cascade**: Jev first, LLM only on the low‑confidence tail — see the companion note.

➡ **Apply to our system:** [`RESEARCH-jev-in-test-agent-v2.md`](RESEARCH-jev-in-test-agent-v2.md)

---

## Sources
- TypeSafe AI — [Introduction docs](https://docs.typesafe.ai/introduction) · [Launch: Introducing System One Models & Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev)
- LangChain — [Building a harness with Jev](https://www.langchain.com/blog/building-a-harness-with-jev) · [Jev for agent evals](https://www.langchain.com/blog/jev-agent-evals-langsmith)
- Arize AI — [Can decision models replace LLM judges?](https://arize.com/blog/typesafe-jev-llm-judge/)
- Independent explainers/reviews — [MindStudio](https://www.mindstudio.ai/blog/jev-system-one-model-launch) · [DataCamp](https://www.datacamp.com/blog/system-one-models-jev) · [explainX](https://www.explainx.ai/blog/typesafe-ai-jev-system-one-models-launch-2026) · [Forkast](https://forkast.news/typesafe-ais-jev-is-not-an-llm-and-that-may-be-the-point/)

> ⚠ Performance/cost/accuracy figures are TypeSafe's own workflow evals (vs LLM averages, not ground truth); one HN reader noted Jev's raw accuracy below Sonnet 5 on the shared chart. Treat as directional, benchmark on our own data before trusting a threshold.
