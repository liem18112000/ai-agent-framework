"""Benchmark a run — freeze its TEV scores into a cached record, and aggregate across runs.

The only place eval reports become persisted `Benchmark` blobs. Compute lives here because it calls
the scoring engines (`evaluate_pack`/`evaluate_plan`); the model + blob I/O live in `common.benchmark`.

- `load_or_compute` — cache-aside: return the saved benchmark, else compute + save. The single choke
  point every tool and the on-finish hook routes through.
- `compute_benchmark` — never raises: a run with nothing to score, or an engine error, yields an
  `ok=false` record (so even a failed run is benchmarked).
- `compare` / `summarize` — read-only aggregation over runs (each computed-if-missing).
"""

from __future__ import annotations

from common.adk.events import now
from common.benchmark import Benchmark, read_benchmark, read_latency, write_benchmark
from common.interrogate.pack import load_pack
from common.memory.bank import ROOT, _slug
from test_evaluation.engine import evaluate_pack, evaluate_plan
from test_evaluation.golden import golden_for, golden_plan_for
from test_evaluation.models import PQSComponents, TPSComponents
from test_evaluation.monitoring import get_logger

log = get_logger("benchmark")

# Source of truth = the component dataclasses, so a new component can't drift out of the tables.
_PQS_KEYS = tuple(PQSComponents().as_dict())
_TPS_KEYS = tuple(TPSComponents().as_dict())


# --- compute + cache -------------------------------------------------------------------------------

def _has_plan(bank, ctx: str) -> bool:
    d = f"{ROOT}/test-plan/{_slug(ctx)}"
    return bool(bank.get_json(f"{d}/plan.json", None) or bank.get_json(f"{d}/scenarios.json", None))


def compute_benchmark(bank, context_id: str) -> Benchmark:
    """Score `context_id` into a Benchmark. Never raises — pqs/tps stay None when there is no pack/plan,
    and any engine error is captured as `ok=false` + `error`."""
    bm = Benchmark(context_id=context_id, computed_at=now())
    try:
        if load_pack(bank, context_id).notes:
            r = evaluate_pack(bank, context_id, golden_for(context_id))
            bm.pqs, bm.pqs_components, bm.seed = r.pqs, r.components.as_dict(), r.seed
            if r.retrieval:
                bm.retrieval = {"precision": r.retrieval.precision, "recall": r.retrieval.recall,
                                "leaked": list(r.retrieval.leaked)}
        if _has_plan(bank, context_id):
            p = evaluate_plan(bank, context_id, golden_plan_for(context_id))
            bm.tps, bm.tps_components = p.tps, p.components.as_dict()
            bm.seed = bm.seed or p.seed
        bm.ok = bm.pqs is not None or bm.tps is not None
        bm.latency_ms = read_latency(context_id)  # server processing time, if a shared cache captured it
        if not bm.ok:
            bm.error = "nothing to score (no pack, no plan)"
    except Exception as exc:  # noqa: BLE001 — a benchmark must always produce a record, even on failure
        bm.ok, bm.error = False, f"{type(exc).__name__}: {exc}"
        log.warning("compute_benchmark %s failed: %s", context_id, exc)
    log.info("compute_benchmark %s: ok=%s pqs=%s tps=%s", context_id, bm.ok, bm.pqs, bm.tps)
    return bm


def load_or_compute(bank, context_id: str, *, recompute: bool = False) -> Benchmark:
    """Return the cached Benchmark (current schema), else compute + save. Covers "if not found,
    calculate then save"."""
    if not recompute:
        cached = read_benchmark(bank, context_id)
        if cached is not None:
            return cached
    bm = compute_benchmark(bank, context_id)
    write_benchmark(bank, bm)
    return bm


# --- rendering + aggregation -----------------------------------------------------------------------

def _fmt(x) -> str:
    return "n/a" if x is None else f"{x:.3f}"


def _components(d: dict) -> str:
    return ", ".join(f"{k}={v:.2f}" for k, v in d.items())


def render_benchmark(bm: Benchmark) -> str:
    if not bm.ok:
        return f"Benchmark {bm.context_id}: FAILED — {bm.error or 'unknown'} (computed {bm.computed_at})"
    lines = [f"Benchmark {bm.context_id} (seed {bm.seed or '-'}, computed {bm.computed_at})",
             f"  PQS: {_fmt(bm.pqs)}   TPS: {_fmt(bm.tps)}"]
    if bm.pqs_components:
        lines.append("  PQS components: " + _components(bm.pqs_components))
    if bm.tps_components:
        lines.append("  TPS components: " + _components(bm.tps_components))
    if bm.retrieval:
        r = bm.retrieval
        lines.append(f"  Retrieval: precision={r['precision']:.2f} recall={r['recall']:.2f} leaked={r['leaked']}")
    return "\n".join(lines)


def _metrics(bm: Benchmark) -> dict:
    """Flat {metric-key: value|None} for table rows — PQS/TPS plus every component."""
    m = {"PQS": bm.pqs, "TPS": bm.tps}
    m.update({f"pqs.{k}": bm.pqs_components.get(k) for k in _PQS_KEYS})
    m.update({f"tps.{k}": bm.tps_components.get(k) for k in _TPS_KEYS})
    return m


def benchmark_run(bank, context_id: str, *, recompute: bool = False) -> str:
    """Tool body for `benchmark_run` — score one run (cache-aside) and render the scorecard."""
    return render_benchmark(load_or_compute(bank, context_id, recompute=recompute))


def compare(bank, context_ids: list[str], *, recompute: bool = False) -> str:
    """Tool body for `compare_benchmarks` — 2+ runs side by side, one metric per row."""
    ids = list(dict.fromkeys(context_ids))  # dedupe, preserve order
    if len(ids) < 2:
        return "Provide at least two DIFFERENT run ids: compare_benchmarks <ctx-a> <ctx-b> ..."
    bms = {c: load_or_compute(bank, c, recompute=recompute) for c in ids}
    mets = {c: _metrics(bms[c]) for c in ids}
    keys = ["PQS", "TPS", *(f"pqs.{k}" for k in _PQS_KEYS), *(f"tps.{k}" for k in _TPS_KEYS)]
    two = len(ids) == 2
    head = "| metric | " + " | ".join(ids) + (" | Δ |" if two else " |")
    sep = "|" + "---|" * (len(ids) + (2 if two else 1))
    lines = [f"# Benchmark compare ({len(ids)} runs)", "", head, sep]
    for key in keys:
        cells = " | ".join(_fmt(mets[c][key]) for c in ids)
        row = f"| {key} | {cells} |"
        if two:
            a, b = mets[ids[0]][key], mets[ids[1]][key]
            delta = _fmt(b - a) if a is not None and b is not None else "n/a"
            row = f"| {key} | {cells} | {delta} |"
        lines.append(row)
    failed = [c for c in ids if not bms[c].ok]
    if failed:
        lines += ["", f"_failed (no score): {', '.join(failed)}_"]
    return "\n".join(lines)


def _agg(label: str, bms: list[Benchmark], attr: str) -> str:
    scored = [bm for bm in bms if getattr(bm, attr) is not None]
    if not scored:
        return f"**{label}**: no scored runs"
    vals = [getattr(bm, attr) for bm in scored]
    best, worst = max(scored, key=lambda b: getattr(b, attr)), min(scored, key=lambda b: getattr(b, attr))
    return (f"**{label}**: mean={sum(vals) / len(vals):.3f} min={min(vals):.3f} max={max(vals):.3f} "
            f"· best={best.context_id} worst={worst.context_id}")


def summarize(bank, k: int = 5, *, recompute: bool = False) -> str:
    """Tool body for `summarize_benchmarks` — the K latest runs (K<10) as a table + PQS/TPS aggregates."""
    if k < 1:
        return "k must be between 1 and 9."
    k = min(k, 9)  # requirement: K < 10
    from common.admin._shared import _run_contexts

    ids = sorted(_run_contexts(bank), key=lambda c: bank.read_refine_state(c).get("now", ""), reverse=True)[:k]
    if not ids:
        return "No runs found (memory/refine/ is empty)."
    bms = [load_or_compute(bank, c, recompute=recompute) for c in ids]
    lines = [f"# Benchmark summary — {len(bms)} latest runs", "",
             "| run | seed | PQS | TPS | ok |", "|---|---|---|---|---|"]
    lines += [f"| {bm.context_id} | {bm.seed or '-'} | {_fmt(bm.pqs)} | {_fmt(bm.tps)} | "
              f"{'yes' if bm.ok else 'no'} |" for bm in bms]
    lines += ["", _agg("PQS", bms, "pqs"), _agg("TPS", bms, "tps")]
    return "\n".join(lines)
