"""Golden JSON → ADK EvalSet/EvalCase (Plan B) + on-disk evalset emitter (E5)."""

from __future__ import annotations

import json
from pathlib import Path

from google.adk.evaluation.eval_case import EvalCase, Invocation
from google.adk.evaluation.eval_set import EvalSet
from google.genai import types

from test_evaluation.golden import load_golden, load_golden_plans

TEST_CONFIG = {"criteria": {"tool_trajectory_avg_score": 1.0, "response_match_score": 0.35}}


def _invocation(seed: str) -> Invocation:
    return Invocation(
        invocation_id=f"inv-{seed}",
        user_content=types.Content(role="user", parts=[types.Part(text=seed)]),
        creation_timestamp=0.0,
    )


def eval_case_for(seed: str) -> EvalCase:
    return EvalCase(eval_id=seed, conversation=[_invocation(seed)], creation_timestamp=0.0)


def pack_eval_set() -> EvalSet:
    cases = [eval_case_for(d["seed"]) for d in load_golden()]
    return EvalSet(eval_set_id="kga-pack", name="KGA pack eval (from golden/)",
                   eval_cases=cases, creation_timestamp=0.0)


def plan_eval_set() -> EvalSet:
    cases = [eval_case_for(d["seed"]) for d in load_golden_plans()]
    return EvalSet(eval_set_id="tpd-plan", name="TPD plan eval (from golden_plans/)",
                   eval_cases=cases, creation_timestamp=0.0)


def write_eval_data(out_dir: str | Path) -> list[Path]:
    """Emit `kga_pack.evalset.json`, `tpd_plan.evalset.json`, and `test_config.json` into `out_dir`."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, es in (("kga_pack", pack_eval_set()), ("tpd_plan", plan_eval_set())):
        p = out / f"{name}.evalset.json"
        p.write_text(es.model_dump_json(indent=2), encoding="utf-8")
        written.append(p)
    cfg = out / "test_config.json"
    cfg.write_text(json.dumps(TEST_CONFIG, indent=2), encoding="utf-8")
    written.append(cfg)
    return written
