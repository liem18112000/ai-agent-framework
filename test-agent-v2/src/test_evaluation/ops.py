"""TEV parsing + report-rendering helpers — framework-neutral (extracted from executor/base.py in C2)."""

from __future__ import annotations

from common.interrogate import present
from test_evaluation.config.layers import PQS_LAYERS, TPS_LAYERS
from test_evaluation.models import EvalReport, PlanReport


def extract_ctx(text: str) -> str | None:
    return present.extract_ctx(text, ("evaluate", "score", "plan", "pack"))


def _is_plan(text: str) -> bool:
    return "plan" in text.lower().split()


def _layer_lines(components: dict, layers: dict) -> list[str]:
    """The 'Components:' block, grouped by evaluation layer (keeps the 'Components:' token callers expect)."""
    out = ["Components:"]
    for label, keys in layers.items():
        out.append(f"  {label}: " + ", ".join(f"{k}={components[k]:.2f}" for k in keys if k in components))
    return out


def render(r: EvalReport) -> str:
    lines = [f"Pack Quality Score for {r.context_id}: {r.pqs}"]
    lines += _layer_lines(r.components.as_dict(), PQS_LAYERS)
    if r.retrieval:
        lines.append(f"  Layer 1 retrieval: recall={r.retrieval.recall:.2f} "
                     f"precision={r.retrieval.precision:.2f} leaked={r.retrieval.leaked}")
    if r.entities and r.entities.missing:
        lines.append("  Layer 1 missing entities: " + ", ".join(r.entities.missing))
    if r.semantic is not None:  # judged tier only — None on the deterministic default path
        lines.append(f"  Layer 1 semantic rubrics: names_the_ac={r.semantic.names_the_ac} "
                     f"declares_gaps_honestly={r.semantic.declares_gaps_honestly}")
    lines.append("  Layer 3 (downstream): noise/topic scored out-of-band; plan quality = sibling TPS")
    return "\n".join(lines)


def render_plan(r: PlanReport) -> str:
    lines = [f"Test-Plan Score for {r.context_id}: {r.tps}"]
    lines += _layer_lines(r.components.as_dict(), TPS_LAYERS)
    if r.scope:
        lines.append(f"  Layer 1 scope: precision={r.scope.precision:.2f} recall={r.scope.recall:.2f} "
                     f"leaked={r.scope.leaked}")
    if r.coverage:
        lines.append(f"  Layer 1 coverage: ac_recall={r.coverage.ac_recall:.2f} "
                     f"matrix={r.coverage.matrix_completeness:.2f} uncovered={r.coverage.uncovered}")
        if r.coverage.traceability < 1.0:  # the traceability gate — surface the untraceable scenarios
            lines.append(f"  Layer 1 traceability: {r.coverage.traceability:.2f} "
                         f"untraceable={r.coverage.untraceable}")
    if r.oracle:
        lines.append(f"  Layer 1 oracle strength: {r.oracle.score:.2f} {r.oracle.distribution}")
    if r.gherkin is not None:
        issues = f", issues={r.gherkin.issues}" if r.gherkin.issues else ""
        lines.append(f"  Layer 1 gherkin: {r.gherkin.scenarios} scenarios, {r.gherkin.tagged} tagged{issues}")
    if r.placeholders and not r.placeholders.passed:
        lines.append(f"  Layer 1 placeholder leak: {r.placeholders.leaked_tokens} (path {r.placeholders.provenance})")
    lines.append("  Layer 3 (downstream): mutation gated on the execution stage — fault_detection is a proxy")
    return "\n".join(lines)
