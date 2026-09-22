"""G4 — calibrate the KGA source-activation gate's run-bar τ against a golden set.

The gate (explore/source_gate.py) SKIPs a source only when JEV is confident AND below the bar:
``conf >= conf_min AND P < τ``. Calibration must sweep τ against the EXACT gate predicate (mirroring
apply_cascade — the same discipline as tools/jev_calibrate.py mirroring loop._decision_gate; a looser
proxy reads a falsely-perfect precision) and report, per τ:

  - take-rate      : fraction of candidate sources the gate would SKIP
  - skip-precision : of the skipped sources, the fraction that were SAFE to skip (would NOT have
                     contributed a golden-relevant node) — the metric to maximise
  - recall-kept    : 1 − (helpful sources skipped / all helpful sources) — MUST stay ≈ 1.0 (I-PG-2)

A row needs a per-source ground truth: ``helps`` = did running this source actually surface ≥1 node in
the ticket's ``relevant_node_ids``? Building the golden (tickets × sources × helps) requires running
each source live against the KGA golden AND a live JEV (TYPESAFE_API_KEY + TPD_DECISION_BACKEND=jev) to
get (P, confidence) per source. Neither is wired yet, so this tool ships the VALIDATED sweep math + a
synthetic self-check; the live collection step is stubbed with the exact shape it must produce.

Run the self-check:  PYTHONIOENCODING=utf-8 uv run python tools/kga_source_gate_calibrate.py
"""

from __future__ import annotations


def sweep(rows: list[dict], *, conf_min: float, taus: list[float]) -> list[dict]:
    """rows: ``[{"source", "P", "conf", "helps"}]`` (one per ticket×candidate-source). Mirror the gate's
    SKIP predicate exactly (``conf >= conf_min AND P < τ``) and score each τ. ``helps`` is the ground
    truth: the source would contribute ≥1 golden-relevant node."""
    total_helpful = sum(1 for r in rows if r["helps"])
    out = []
    for tau in taus:
        skipped = [r for r in rows if r["conf"] >= conf_min and r["P"] < tau]  # the gate's ONLY skip
        bad = [r for r in skipped if r["helps"]]  # skipped a source that WOULD have helped → recall loss
        take_rate = len(skipped) / len(rows) if rows else 0.0
        skip_precision = 1.0 - len(bad) / len(skipped) if skipped else 1.0
        recall_kept = 1.0 - len(bad) / total_helpful if total_helpful else 1.0
        out.append({"tau": round(tau, 3), "take_rate": round(take_rate, 3),
                    "skip_precision": round(skip_precision, 3), "recall_kept": round(recall_kept, 3),
                    "n_skipped": len(skipped), "bad_skips": len(bad)})
    return out


def best_tau(scored: list[dict], *, min_recall_kept: float = 1.0) -> dict | None:
    """Pick the τ with the highest take-rate whose recall-kept meets the floor (default: lose NO helpful
    source). None = no τ trims anything without dropping recall — the 'leave the gate OFF' verdict."""
    safe = [s for s in scored if s["recall_kept"] >= min_recall_kept and s["n_skipped"] > 0]
    return max(safe, key=lambda s: (s["take_rate"], s["tau"])) if safe else None  # tie → larger τ (headroom)


def _demo() -> None:
    """Self-check the sweep math on synthetic rows (no JEV, no golden needed)."""
    taus = [0.3, 0.4, 0.5, 0.6]
    rows = [
        # confident + genuinely unhelpful → the ideal skip (safe at any τ > its P)
        {"source": "cloud_discover", "P": 0.10, "conf": 0.9, "helps": False},
        {"source": "atlassian_search", "P": 0.20, "conf": 0.8, "helps": False},
        # confident + ACTUALLY helpful, mid P → skipped only once τ climbs past 0.45 → a recall loss then
        {"source": "ground_leads", "P": 0.45, "conf": 0.9, "helps": True},
        # helpful, high P → never skipped
        {"source": "semantic", "P": 0.95, "conf": 0.9, "helps": True},
        # low confidence → never skipped regardless of P (the cascade's fallback)
        {"source": "atlassian_search", "P": 0.05, "conf": 0.2, "helps": True},
    ]
    scored = sweep(rows, conf_min=0.4, taus=taus)
    by_tau = {s["tau"]: s for s in scored}

    # τ=0.3: skips only the two confident-unhelpful (P<0.3) → 2 safe skips, no recall loss.
    assert by_tau[0.3]["n_skipped"] == 2 and by_tau[0.3]["bad_skips"] == 0
    assert by_tau[0.3]["skip_precision"] == 1.0 and by_tau[0.3]["recall_kept"] == 1.0
    # τ=0.5: now also skips the confident-helpful ground_leads (P=0.25<0.5) → 1 bad skip, recall drops.
    assert by_tau[0.5]["bad_skips"] == 1 and by_tau[0.5]["recall_kept"] < 1.0
    # even at τ=0.6 nothing new is skipped beyond τ=0.5's set — the low-confidence row (conf 0.2 < 0.4)
    # is never a candidate, so take-rate plateaus.
    assert by_tau[0.6]["n_skipped"] == by_tau[0.5]["n_skipped"]
    # best τ keeping ALL helpful sources = the largest safe τ (0.4 here: skips the 2 unhelpful, P 0.1/0.2<0.4).
    best = best_tau(scored, min_recall_kept=1.0)
    assert best is not None and best["tau"] == 0.4 and best["bad_skips"] == 0
    print("self-check OK — sweep mirrors the gate's SKIP predicate; best recall-safe τ =", best["tau"])


def main() -> None:
    _demo()
    print("\nLIVE calibration is NOT wired — it needs, per candidate source × golden ticket:")
    print("  1. run the source live against the KGA golden → helps = (its seeds ∩ relevant_node_ids) ≠ ∅")
    print("  2. a live JEV (TYPESAFE_API_KEY + TPD_DECISION_BACKEND=jev) → (P, confidence) via noul")
    print("  then: rows → sweep(rows, conf_min=0.40, taus=[.3..7]) → best_tau(min_recall_kept=1.0).")
    print("Expect the JEV accept-side asymmetry (J4) to yield best_tau = None → leave the gate OFF.")


if __name__ == "__main__":
    main()
