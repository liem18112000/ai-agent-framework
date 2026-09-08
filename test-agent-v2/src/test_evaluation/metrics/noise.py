"""Noise Sensitivity — the memory-bleed metric at the OUTPUT level."""

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
