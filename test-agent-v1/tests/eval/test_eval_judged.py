"""E2 + E3 + E4 — the judged / composite tier (nightly, or on the `eval:` PR label).

E2 (RAGAS faithfulness/relevancy over the understanding) needs the optional `ragas` extra + a
Vertex judge, so those tests SKIP cleanly when it isn't installed. E3 (entity recall, noise
sensitivity, topic adherence) and E4 (PQS, rubrics, history) are DETERMINISTIC and always run —
they score the SAME real understanding an LLM judge would, driven fully offline.
"""

from __future__ import annotations

import pytest

from test_evaluation.golden import load_golden
from test_evaluation.metrics import ragas_judge
from test_evaluation.metrics.entities import entities_recall
from test_evaluation.metrics.history import append_run, load_history, regressed
from test_evaluation.metrics.node_overlap import retrieval_scores
from test_evaluation.metrics.noise import drift_score
from test_evaluation.metrics.pqs import pqs
from test_evaluation.metrics.rubrics import cites_only_real_ids, no_invented_urls
from test_evaluation.metrics.topic import adherence_curve
from test_evaluation.metrics.trajectory import trajectory_score
from test_evaluation.models import PQSComponents
from tests.eval.harness import (
    RecordedAtlassianClient,
    load_atlassian_fixture,
    recorded_client,
    run_gather_offline,
    run_refine_offline,
)

_CASES = load_golden()
_IDS = [c["seed"] for c in _CASES]


@pytest.fixture(scope="module", params=_CASES, ids=_IDS)
def refined(request):
    """Gather + refine one golden seed offline; expose the pack + understanding a judge scores."""
    case = request.param
    t = run_gather_offline(case["seed"], client=recorded_client(case["fixture"]),
                           text=f"gather {case['seed']} depth {case['depth']}")
    t.understanding = run_refine_offline(t.bank, t.context_id, seed=f"jira:{case['seed']}").understanding
    return case, t


# --- E3: entity recall (deterministic) --- #
def test_entities_recall(refined):
    case, t = refined
    e = entities_recall(t.node_texts, case["key_entities"])
    assert e.recall >= 0.8, f"{case['seed']}: entities missing {e.missing}"


# --- E4: rubrics on the real understanding (deterministic) --- #
def test_rubric_no_fabrication(refined):
    case, t = refined
    assert cites_only_real_ids(t.understanding, t.node_ids).passed, \
        f"{case['seed']}: understanding cites a non-pack Jira id"
    assert no_invented_urls(t.understanding, " ".join(t.node_texts)).passed


# --- E4: PQS composite from the real per-seed components (deterministic) --- #
def test_pqs_composite(refined):
    case, t = refined
    s = retrieval_scores(t.node_ids, set(case["relevant_node_ids"]),
                         set(case["must_not_retrieve_ids"]))
    components = PQSComponents(
        faithfulness=float(cites_only_real_ids(t.understanding, t.node_ids).passed),
        ctx_precision=s.precision,
        ctx_recall=s.recall,
        relevancy=entities_recall(t.node_texts, case["key_entities"]).recall,
        trajectory=trajectory_score(t.tiers, case["expected_tiers"], "in_order"),
    )
    out = pqs(components)
    assert out.components is components                                      # always carries them
    assert out.pqs >= 0.8, f"{case['seed']}: PQS {out.pqs} — {out.components}"


# --- E3: noise sensitivity (deterministic counterfactual) --- #
def test_noise_sensitivity_output_level():
    """Inject an unrelated node INTO the pack (same run_id) and confirm the understanding does not
    absorb it — the output-level bleed guard, complementary to E1's retrieval-level precision."""
    clean = run_gather_offline("LUZ-701", client=recorded_client("eval_bleed"),
                               text="gather LUZ-701 depth 1", context_id="bleed-clean")
    und_a = run_refine_offline(clean.bank, "bleed-clean", seed="jira:LUZ-701").understanding

    data = load_atlassian_fixture("eval_bleed")   # link the hard-negative so it enters the pack
    data["issues"]["LUZ-701"]["fields"]["issuelinks"].append(
        {"type": {"name": "Relates"}, "outwardIssue": {"key": "LUZ-799"}})
    noisy = run_gather_offline("LUZ-701", client=RecordedAtlassianClient(data),
                               text="gather LUZ-701 depth 1", context_id="bleed-noisy")
    assert "jira:LUZ-799" in noisy.node_ids                       # the noise really is in the pack
    und_b = run_refine_offline(noisy.bank, "bleed-noisy", seed="jira:LUZ-701").understanding

    d = drift_score(und_a, und_b, ["ZIP import", "address enrichment"])
    assert d.noise_sensitivity == 0.0, f"understanding absorbed noise: {d.leaked_terms}"


# --- E3: topic adherence helper (deterministic) --- #
def test_topic_adherence_curve():
    seed_terms = {"invoice", "charge", "luz_finance"}
    assert adherence_curve([["invoice job"], ["charge run"]], seed_terms) == [1.0, 1.0]
    drift = adherence_curve([["invoice"], ["zip import"], ["address map"]], seed_terms)
    assert drift[0] == 1.0 and drift[-1] == 0.0                   # monotone decline = drift


# --- E2: RAGAS faithfulness/relevancy (LLM — skips without the [eval] extra) --- #
def test_ragas_faithfulness_relevancy(refined):
    if not ragas_judge.available():
        pytest.skip("ragas not installed — runs only in the nightly/[eval] job")
    case, t = refined
    scores = ragas_judge.judge(seed_summary=f"Test plan for {case['seed']}",
                               understanding=t.understanding, note_synopses=t.node_texts,
                               reference=case["reference_understanding"])
    assert scores.faithfulness >= 0.5


# --- E4: history append round-trip + regression band (deterministic) --- #
def test_history_round_trip(tmp_path):
    p = tmp_path / "history.jsonl"
    append_run(p, timestamp="2026-09-04T00:00:00Z", commit="a", pqs=0.90, components={}, per_seed={})
    append_run(p, timestamp="2026-09-05T00:00:00Z", commit="b", pqs=0.84, components={}, per_seed={})
    hist = load_history(p)
    assert len(hist) == 2 and hist[-1].pqs == 0.84
    assert regressed(hist[-1].pqs, hist[0].pqs, band=0.05)   # 0.90 → 0.84 trips the alert
