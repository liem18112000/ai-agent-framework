"""G4-LIVE — calibrate the KGA source-gate τ with REAL JEV over the KGA goldens.

The stub in ``kga_source_gate_calibrate.py`` shipped the sweep math + a synthetic self-check but left
live collection unwired. This wires the collection: for each golden ticket × candidate source it gets
a live JEV ``noul`` (P, confidence) on the SAME ``_STATEMENTS`` the production gate uses, and pairs it
with a ``helps`` ground truth grounded in the golden's node KINDS:

  All three goldens' ``relevant_node_ids`` are ``jira:`` nodes → only ``atlassian_search`` can surface
  them. ``semantic`` starts cold (fresh bank), ``ground_leads`` (external) and ``cloud_discover``
  (codegraph/services) produce no node of a golden-relevant kind here. So helps = {atlassian_search:
  True, else False}. (Coarser than a per-source ablation, but grounded in the real goldens, not hand
  labels; the ablation collector is the heavier follow-up.)

Then it reuses ``sweep``/``best_tau`` verbatim. N=3×4=12 (J4-order) — enough to see whether a
recall-safe τ exists, NOT to bless a production τ on its own. Needs TYPESAFE_API_KEY (loaded from .env).

Run: PYTHONIOENCODING=utf-8 uv run python tools/kga_source_gate_calibrate_live.py
"""

from __future__ import annotations

import os
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT / "tools"))

# offline hygiene: JEV needs TYPESAFE_API_KEY, but nothing here needs Vertex — clear it so an import
# side effect can't dial Vertex (dotenv-leaks-VERTEX gotcha). Load .env AFTER for the JEV key.
for _k in ("VERTEX_PROJECT", "VERTEX_LOCATION", "VERTEX_MODEL"):
    os.environ[_k] = ""
try:
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")
except ImportError:
    pass

import kga_source_gate_calibrate as g4

from common.adk.providers.jev import JevProvider
from knowledge_gathering.gather.explore.source_gate import _STATEMENTS

# Golden ticket states (from tests/eval/fixtures/atlassian/*.json summaries). A compact stand-in for
# the production _gate_state(seed, terms, project, thin) — seed + the real summary + sibling terms.
_GOLDENS = [
    ("LUZ-501", "Invoice charge job for luz_finance; dunning status persistence in the database; "
     "sandbox payment processor test-mode check. Domain: billing / finance / dunning."),
    ("LUZ-601", "Umbrella: trigger enricher regarding document type; epic: document enrichment writes "
     "enrichmentstatus to the jsonstore. Domain: document enrichment / jsonstore."),
    ("LUZ-701", "QR-bill fallback removal (individual customers only); failCount is the day-of-month of "
     "the dunning run. Domain: billing / QR-bill / dunning."),
]
# helps ground truth per source, grounded in golden node kinds (all relevant_node_ids are jira:).
_HELPS = {"atlassian_search": True, "semantic": False, "ground_leads": False, "cloud_discover": False}
_SOURCES = list(_HELPS)


def collect(provider) -> list[dict]:
    rows = []
    for seed, summary in _GOLDENS:
        state = f"Ticket {seed}: {summary}"
        for src in _SOURCES:
            v = provider.noul(state, _STATEMENTS[src])
            p = (v.probs or {}).get("true", float(bool(v.value)))
            rows.append({"ticket": seed, "source": src, "P": round(p, 3),
                         "conf": round(v.confidence, 3), "helps": _HELPS[src]})
    return rows


def main() -> int:
    provider = JevProvider()
    if not provider.is_configured():
        print("JEV not configured: set TYPESAFE_API_KEY (.env) + install the `jev` extra.", file=sys.stderr)
        return 2

    rows = collect(provider)
    print("=== live JEV per golden ticket × source (P(true), conf) ===")
    print(f"{'ticket':10} {'source':18} {'P':>6} {'conf':>6} {'helps':>6}")
    for r in rows:
        print(f"{r['ticket']:10} {r['source']:18} {r['P']:>6.2f} {r['conf']:>6.2f} {r['helps']!s:>6}")

    conf_min = float(os.environ.get("KGA_SOURCE_GATE_CONF_MIN", "0.40"))
    taus = [0.30, 0.40, 0.50, 0.60, 0.70]
    scored = g4.sweep(rows, conf_min=conf_min, taus=taus)
    print(f"\n=== τ sweep (gate SKIP = conf >= {conf_min} AND P < τ), N={len(rows)} ===")
    print(f"{'tau':>5} {'take':>6} {'skip_prec':>10} {'recall_kept':>12} {'n_skip':>7} {'bad':>4}")
    for s in scored:
        print(f"{s['tau']:>5.2f} {s['take_rate']:>6.2f} {s['skip_precision']:>10.2f} "
              f"{s['recall_kept']:>12.2f} {s['n_skipped']:>7} {s['bad_skips']:>4}")

    best = g4.best_tau(scored, min_recall_kept=1.0)
    print("\n=== VERDICT ===")
    if best is None:
        print("best_tau = None → no τ skips anything without losing a helpful source. KEEP THE GATE OFF.")
    else:
        print(f"best recall-safe τ = {best['tau']} (conf_min={conf_min}): skips {best['n_skipped']}/{len(rows)} "
              f"sources, skip-precision {best['skip_precision']:.2f}, recall-kept {best['recall_kept']:.2f}, "
              f"0 helpful sources dropped.")
        print(f"  → set kga_source_gate=true, kga_source_gate_conf_min={conf_min}, kga_source_gate_tau={best['tau']}")
    print("\nCAVEAT: N=12, helps grounded in golden node KINDS (not a per-source ablation). Small-N — "
          "treat τ as a starting point, re-run with the ablation collector before trusting in prod.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
