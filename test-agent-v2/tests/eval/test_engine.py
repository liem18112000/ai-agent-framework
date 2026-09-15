"""Tests for the test_evaluation agent surface — the engine + the ADK EvaluatorAgent."""

from __future__ import annotations

from test_evaluation.engine import evaluate_pack
from test_evaluation.models import EvalCase
from tests.conftest import drive_adk
from tests.eval.harness import (
    RecordedAtlassianClient,
    load_atlassian_fixture,
    recorded_client,
    run_gather_offline,
    run_refine_offline,
)


def _refined(seed, fixture, ctx, *, client=None):
    """A bank holding a gathered + refined pack for `ctx` (run_id == ctx)."""
    t = run_gather_offline(seed, client=client or recorded_client(fixture),
                           text=f"gather {seed} depth 1", context_id=ctx)
    run_refine_offline(t.bank, ctx, seed=f"jira:{seed}")
    return t.bank


def test_evaluate_pack_scores_a_clean_pack():
    bank = _refined("LUZ-501", "eval_rich", "LUZ-501")
    case = EvalCase.from_dict({"seed": "LUZ-501",
                               "relevant_node_ids": ["jira:LUZ-501", "jira:LUZ-502", "jira:LUZ-503"],
                               "key_entities": ["luz_finance", "Dunning"]})
    r = evaluate_pack(bank, "LUZ-501", case)
    assert r.retrieval.recall == 1.0 and r.retrieval.leaked == []
    assert r.rubrics.cites_only_real_ids.passed
    assert r.pqs >= 0.8


def test_evaluate_pack_flags_a_leak():
    data = load_atlassian_fixture("eval_bleed")
    data["issues"]["LUZ-701"]["fields"]["issuelinks"].append(
        {"type": {"name": "Relates"}, "outwardIssue": {"key": "LUZ-799"}})
    bank = _refined("LUZ-701", "eval_bleed", "LUZ-701", client=RecordedAtlassianClient(data))
    case = EvalCase.from_dict({"seed": "LUZ-701", "relevant_node_ids": ["jira:LUZ-701", "jira:LUZ-702"],
                               "must_not_retrieve_ids": ["jira:LUZ-799"]})
    r = evaluate_pack(bank, "LUZ-701", case)
    assert r.retrieval.leaked == ["jira:LUZ-799"]


async def test_agent_evaluates_pack_by_ctx(monkeypatch):
    import test_evaluation.agent as agent_mod

    bank = _refined("LUZ-501", "eval_rich", "LUZ-501")
    monkeypatch.setattr(agent_mod, "build_bank", lambda: bank)
    out = await drive_adk(agent_mod.build_root_agent, "evaluate LUZ-501", session_id="LUZ-501")
    assert "Pack Quality Score for LUZ-501" in out and "Components:" in out


def test_extract_ctx_handles_three_token_plan_command():
    """M1: `evaluate plan <ctx>` is 3 tokens — must return the ctx, not the literal 'plan'."""
    from test_evaluation.ops import extract_ctx

    assert extract_ctx("evaluate plan LUZ-158390") == "LUZ-158390"  # was "plan" before the fix
    assert extract_ctx("evaluate plan run-abc123") == "run-abc123"
    assert extract_ctx("score pack LUZ-9") == "LUZ-9"
    assert extract_ctx("evaluate LUZ-501") == "LUZ-501"  # 2-token command still works


def test_evaluate_pack_url_check_uses_pack_summary_not_titles(monkeypatch):
    """M2: a URL that lives in a note synopsis (not its title) is grounded, not 'invented'."""
    import test_evaluation.engine.loaders as loaders
    from common.models import Note, Pack

    url = "https://axonivy.atlassian.net/browse/LUZ-501"
    pack = Pack(context_id="LUZ-501",
                notes=[Note(id="jira:LUZ-501", type="jira-issue", title="Dunning", synopsis=f"see {url}")])
    monkeypatch.setattr(loaders, "load_pack", lambda bank, ctx: pack)  # pack_view() reads it here now
    bank = type("_B", (), {"read_understanding": lambda self, ctx: f"Grounded per {url}"})()
    r = evaluate_pack(bank, "LUZ-501")
    assert r.rubrics.no_invented_urls.passed and r.rubrics.no_invented_urls.invented == []
