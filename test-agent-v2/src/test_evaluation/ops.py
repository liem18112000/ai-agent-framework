"""TEV parsing + report-rendering helpers — framework-neutral (extracted from executor/base.py in C2)."""

from __future__ import annotations

from common.interrogate import present
from test_evaluation.models import EvalReport, PlanReport


def extract_ctx(text: str) -> str | None:
    return present.extract_ctx(text, ("evaluate", "score", "plan", "pack"))


def _is_plan(text: str) -> bool:
    return "plan" in text.lower().split()


def render(r: EvalReport) -> str:
    lines = [
        f"Pack Quality Score for {r.context_id}: {r.pqs}",
        "Components: " + ", ".join(f"{k}={v:.2f}" for k, v in r.components.as_dict().items()),
    ]
    if r.retrieval:
        lines.append(f"Retrieval: recall={r.retrieval.recall:.2f} "
                     f"precision={r.retrieval.precision:.2f} leaked={r.retrieval.leaked}")
    if r.entities and r.entities.missing:
        lines.append("Missing entities: " + ", ".join(r.entities.missing))
    if r.semantic is not None:  # judged tier only — None on the deterministic default path
        lines.append(f"Semantic rubrics: names_the_ac={r.semantic.names_the_ac} "
                     f"declares_gaps_honestly={r.semantic.declares_gaps_honestly}")
    return "\n".join(lines)


def render_plan(r: PlanReport) -> str:
    lines = [
        f"Test-Plan Score for {r.context_id}: {r.tps}",
        "Components: " + ", ".join(f"{k}={v:.2f}" for k, v in r.components.as_dict().items()),
    ]
    if r.scope:
        lines.append(f"Scope: precision={r.scope.precision:.2f} recall={r.scope.recall:.2f} "
                     f"leaked={r.scope.leaked}")
    if r.coverage:
        lines.append(f"Coverage: ac_recall={r.coverage.ac_recall:.2f} "
                     f"matrix={r.coverage.matrix_completeness:.2f} uncovered={r.coverage.uncovered}")
    if r.oracle:
        lines.append(f"Oracle strength: {r.oracle.score:.2f} {r.oracle.distribution}")
    if r.placeholders and not r.placeholders.passed:
        lines.append(f"Placeholder leak: {r.placeholders.leaked_tokens} (path {r.placeholders.provenance})")
    return "\n".join(lines)
