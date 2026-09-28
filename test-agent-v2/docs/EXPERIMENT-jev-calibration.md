# Live JEV calibration — `TPD_DECISION_CONF_MIN`

*2026-09-22 · branch `experiment/jev-decision-provider` · companion to [`EXPERIMENT-jev-results.md`](EXPERIMENT-jev-results.md) (the earlier **modeled/offline** run) and [`RESEARCH-jev-in-test-agent-v2.md`](RESEARCH-jev-in-test-agent-v2.md).*

Runs against **real JEV** (`typesafe-sdk` 0.7.1) and the **real LLM judge** (Vertex Claude), i.e. rollout step 2's "calibrate the threshold on the goldens." Harness: `tools/jev_calibrate.py`.

## Method
Reference oracle = the production LLM judge (`assured.loop.judge_once`, median-of-3). For each golden plan (`LUZ-701`/`LUZ-501`/`LUZ-601`) we build quality variants and score each two ways on the **byte-identical** `suite_state` the gate uses: JEV `score()` → (score, confidence), LLM judge → reference score. `accept = score ≥ 0.7`. `agree = (jev_accept == llm_accept)`.

**The sweep mirrors the production gate** (`loop._decision_gate`): the fast path fires **only on confident ACCEPTS** — `jev_acc AND conf ≥ τ` — a JEV *reject* never short-circuits (the LLM judge always runs on rejects, because its textual issues/reflections are needed to regenerate). So `accept-prec` = correct-accept rate over the *fired* rows; `take-rate` = |fired|/N. Counting confident rejects here would inflate precision — see run 1's mistake below.

Two changes from run 1: (1) a **`drop1`** variant (full minus one scenario) — the near-accept borderline probe, the point most likely to make JEV and the LLM diverge; (2) the **gate-accurate sweep** above (run 1 swept `conf ≥ τ` over *all* rows, including rejects).

## Run history
- **Run 1 (N=12)** — invalidated twice: first by the `loads_obj` tool-call-envelope bug (every LLM verdict forced to 0.0), then, after that fix, by a **methodology bug**: the sweep counted confident *rejects* as fast-path wins, so precision read 1.00 at every τ. Superseded.
- **Run 2 (N=15) — authoritative, below.** Adds `drop1`, fixes the sweep to the accept-only gate. Now has real divergence (4 disagreements) and a gate-accurate sweep.

## Results — run 2 (N=15, 2026-09-22)

| item | jev_score | conf | llm | jev_acc | llm_acc | agree |
|---|---|---|---|---|---|---|
| LUZ-701/full | 0.69 | 0.33 | 0.68 | False | False | ✓ |
| LUZ-701/drop1 | 0.71 | 0.31 | 0.58 | **True** | False | ✗ false-accept |
| LUZ-701/half | 0.60 | 0.54 | 0.34 | False | False | ✓ |
| LUZ-701/one | 0.20 | 0.70 | 0.18 | False | False | ✓ |
| LUZ-701/mismatch | 0.04 | 0.94 | 0.03 | False | False | ✓ |
| LUZ-501/full | 0.74 | 0.26 | 0.90 | **True** | **True** | ✓ (the one correct accept) |
| LUZ-501/drop1 | 0.69 | 0.41 | 0.72 | False | **True** | ✗ false-reject |
| LUZ-501/half | 0.54 | 0.80 | 0.50 | False | False | ✓ |
| LUZ-501/one | 0.17 | 0.74 | 0.18 | False | False | ✓ |
| LUZ-501/mismatch | 0.02 | 0.97 | 0.03 | False | False | ✓ |
| LUZ-601/full | 0.79 | 0.36 | 0.58 | **True** | False | ✗ false-accept |
| LUZ-601/drop1 | 0.69 | 0.38 | 0.72 | False | **True** | ✗ false-reject |
| LUZ-601/half | 0.52 | 0.60 | 0.55 | False | False | ✓ |
| LUZ-601/one | 0.28 | 0.59 | 0.18 | False | False | ✓ |
| LUZ-601/mismatch | 0.01 | 0.98 | 0.05 | False | False | ✓ |

**Overall agreement 11/15.** The `drop1` probe did its job — 3 of the 4 disagreements land on it (the accept boundary). The three **JEV-accept** rows (the only ones production can fast-path) are `701/drop1` (0.31, wrong), `501/full` (0.26, right), `601/full` (0.36, wrong).

### Gate-accurate sweep (fast path = confident ACCEPTS only)

| τ_conf | take-rate | accept-prec | n_fired |
|---|---|---|---|
| 0.20 | 20% | 0.33 | 3 |
| 0.25 | 20% | 0.33 | 3 |
| 0.30 | 13% | 0.00 | 2 |
| 0.35 | 7% | 0.00 | 1 |
| **0.40 – 0.95** | **0%** | **n/a** | **0** |

**There is no τ that pays off.** Above τ=0.40 the fast path *never fires* (no JEV-accept clears conf 0.40) → JEV is pure overhead, always falling back to the LLM. Below that it only fires on false-accepts (precision 0.00 at τ 0.30–0.36; 0.33 at τ≤0.26 = ships a bad suite). J4's exit criterion — *a τ with accept-precision ≥0.90 at a useful take-rate, on divergent + accept-side data* — is now **tested and fails**.

### The two J4 blockers, answered with data
- **Confidence on correct accepts:** the rows the LLM judge accepted (n=3) carry conf **min 0.26 / mean 0.35 / max 0.41**, and JEV agreed on only **1 of 3**. JEV is both *unsure* and *unreliable* on accepts.
- **Latency:** JEV `score()` **0.77 s** vs LLM judge median-of-3 **40.1 s** → ~39 s saved *per gate the fast path takes*. Real, but unreachable on the accept side (take-rate 0% at any safe τ).

## Read — where the win actually is
The confidence signal is **strong and correct on the reject side and weak on the accept side**: JEV rejects the `mismatch`/`one` suites at conf 0.70–0.98, all correct; it accepts only at conf ≤0.36, half wrong. This matches the design asymmetry — JEV scores `pack summary + [kind] title` bullets while the LLM judge reads full scenario **steps**, so JEV is structurally under-informed on exactly the accept call.

Consequence: the current gate captures the *accept* side (which doesn't work) and ignores the *reject* side (which does). Run 1's misleading "60% take @ 1.00 precision" was in fact **9 confident, correct rejects** — the real opportunity, which the accept-only gate throws away.

## Decision
- **Keep the feature OFF.** The accept-side fast path cannot be calibrated to pay off on this data — no safe τ exists.
- **τ stays at the conservative 0.80 default** (moot: take-rate is 0% there regardless).
- **Do not just "widen goldens and re-run the same design."** The blocker is not N — it is the accept-side confidence asymmetry. Two design forks worth a spike before more calibration (both are J7 / design, not more of J4):
  1. **Feed JEV judge-equivalent state** (full scenario steps, not title bullets) and re-calibrate — directly tests the asymmetry hypothesis; the promising path to lift accept confidence.
  2. **Reject-side cascade** — a confident JEV *reject* skips the LLM judge and goes straight to regenerate. That is where JEV is confident+correct and where most early assured-loop rounds live. Needs a design change: regeneration currently consumes the LLM judge's textual issues, which a JEV reject doesn't carry.

## Honest limits (still open)
1. **N=15, synthetic degradation, 3 goldens.** Enough to *disprove* the accept fast-path (a clean negative), not to bless any τ. Real good/bad suites would sharpen the reject-side numbers.
2. **Confidence is per-model.** JEV early-access; re-check on any model update.
