"""E5 — canonical `adk eval` data: emitted `*.evalset.json` + `test_config.json` are well-formed,"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from google.adk.evaluation.eval_set import EvalSet

from test_evaluation.eval.evalset import TEST_CONFIG, write_eval_data
from test_evaluation.eval.runner import DATA_DIR, creds_available, run_agent_eval


def test_emitted_evalsets_are_well_formed(tmp_path):
    written = {p.name for p in write_eval_data(tmp_path)}
    assert written == {"kga_pack.evalset.json", "tpd_plan.evalset.json", "test_config.json"}

    es = EvalSet.model_validate_json((tmp_path / "kga_pack.evalset.json").read_text(encoding="utf-8"))
    assert len(es.eval_cases) >= 3
    case = es.eval_cases[0]
    assert case.conversation[0].user_content.parts[0].text == case.eval_id

    cfg = json.loads((tmp_path / "test_config.json").read_text(encoding="utf-8"))
    assert cfg == TEST_CONFIG
    assert "tool_trajectory_avg_score" in cfg["criteria"]


def test_committed_data_dir_is_present_and_loads():
    for name in ("kga_pack.evalset.json", "tpd_plan.evalset.json"):
        EvalSet.model_validate_json((DATA_DIR / name).read_text(encoding="utf-8"))
    assert (DATA_DIR / "test_config.json").exists()


@pytest.mark.skipif(creds_available(), reason="live AgentEvaluator run needs no assertion here")
async def test_agent_eval_harness_skips_without_creds():
    """Offline, the canonical AgentEvaluator harness is not exercised (it runs the real agent)."""
    assert not creds_available()
    assert callable(run_agent_eval)
    assert Path(DATA_DIR).is_dir()
