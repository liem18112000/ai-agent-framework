"""Noise Sensitivity — the memory-bleed metric at the OUTPUT level.

Precision (node_overlap) catches an irrelevant node being RETRIEVED; this catches whether it
actually CHANGED the understanding — the real bleed incident. `drift_score` is the deterministic
counterfactual proxy: run refine on a clean pack, inject ONE hard-negative node, re-run, and
measure how many of the injected node's terms leaked into the new understanding but weren't in the
clean one. 0.0 = the agent ignored the noise (good); higher = noise-sensitive. Causal, not
correlational — toggle a de-bias flag (B4/B5) and watch the injected terms stop leaking.
"""

from __future__ import annotations

from test_evaluation.models import NoiseScore


def drift_score(baseline: str, perturbed: str, injected_terms: list[str]) -> NoiseScore:
    """Fraction of `injected_terms` that surfaced in `perturbed` but NOT `baseline`. 0.0 = noise ignored."""
    b, p = baseline.lower(), perturbed.lower()
    leaked = [t for t in injected_terms if t.lower() in p and t.lower() not in b]
    return NoiseScore(
        noise_sensitivity=len(leaked) / len(injected_terms) if injected_terms else 0.0,
        leaked_terms=leaked,
    )
