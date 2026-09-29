"""Throwaway JEV-cascade measurement harness (offline, no network). NOT a pytest module.

Measures the JEV decision-cascade win by SPYING on the real code paths (no reimplementation):
  * Experiment A — the always-on assured loop (`run_assured_scenarios` via `implement_plan`):
    counts LLM judge calls (`judge_once` invocations) under baseline / accept-fast / fallback.
  * Experiment B — TEV `build_semantic_judge`: counts `provider.complete` LLM calls under
    baseline vs JEV-noul, and checks the JEV bool matches P(true) >= 0.5.
  * Deploy-safety smoke — `main.build_app` boots with the backend unset AND with
    TPD_DECISION_BACKEND=jev but no TYPESAFE_API_KEY (JevProvider.is_configured() must be False).

There is NO real JEV endpoint (JevProvider is a raising stub) and NO real LLM offline, so the fast
path is served by the existing `FakeDecisionProvider` (calibrated Verdicts) and the LLM path by the
existing offline fake models. Latency/cost figures are MODELED = vendor per-call figures × measured
call counts (see docs/RESEARCH-typesafe-jev.md), never measured wall-clock.

Run: PYTHONIOENCODING=utf-8 uv run python tools/jev_experiment.py
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import sys

# --- offline hygiene: set BEFORE importing the agent packages (they load_dotenv at import) --------
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
for _k in ("VERTEX_PROJECT", "VERTEX_LOCATION", "VERTEX_MODEL", "CACHE_BACKEND"):
    os.environ[_k] = ""  # vertex_config() falsy -> heuristic path; NullCache -> no Redis
os.environ["ALLOW_INSECURE"] = "1"  # offline apps have no bearer set
os.environ.pop("TPD_JUDGE_SAMPLES", None)  # let the PRODUCTION default (3) apply to the baseline
os.environ.pop("TPD_LLM_DETAIL", None)
os.environ.pop("TPD_DECISION_BACKEND", None)

_ROOT = pathlib.Path(__file__).resolve().parents[1]  # test-agent-v2/
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT))  # so `import tests.conftest` resolves (namespace pkg, no __init__)

import common.adk.providers as providers_mod
import test_plan_definition.implement.assured.loop as loop_mod
from common.adk.providers.decision import Verdict
from common.memory import MemoryBank
from common.testplan.models import CONFIRMED
from test_evaluation.eval import judge as judge_mod
from test_plan_definition.define import define
from test_plan_definition.implement import implement_plan
from tests.conftest import FakeDecisionProvider, load_fixture_bucket
from tests.tpd_fakes import full_fake_model

_ORIG_GET_DECISION = providers_mod.get_decision_provider
_ORIG_TEV_GET_PROVIDER = judge_mod.get_provider


# --- doubles ------------------------------------------------------------------------------------
class RecordingDecision(FakeDecisionProvider):
    """FakeDecisionProvider that records the `state` passed to score() (to size the JEV input)."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.states: list[str] = []

    def score(self, state, instructions, levels):
        self.states.append(state)
        return super().score(state, instructions, levels)


class FakeModelProvider:
    """A configured ModelProvider double whose `complete` calls are counted (never hits network).

    Mirrors tests/eval/test_judge.py::_FakeProvider — the real TEV LLM-judge path calls
    provider.complete(prompt, max_tokens=8)."""

    name = "claude"

    def __init__(self, answer="yes"):
        self.answer = answer
        self.prompts: list[str] = []

    def is_configured(self) -> bool:
        return True

    def complete(self, prompt: str, *, max_tokens: int) -> str:
        self.prompts.append(prompt)
        return self.answer


# --- Experiment A: assured loop -----------------------------------------------------------------
async def _fresh_confirmed_bank() -> MemoryBank:
    bank = MemoryBank(load_fixture_bucket("pack_run-6f2a"))
    result = await define(bank, "run-6f2a", seed="LUZ-158390")
    assert result.plan.status == CONFIRMED, f"define did not confirm: {result.plan.status}"
    return bank


async def run_config_A(label: str, decision_factory) -> dict:
    """Drive one implement_plan run; spy on judge_once invocations on the REAL loop path."""
    bank = await _fresh_confirmed_bank()
    fake = full_fake_model()

    calls = {"judge_once": 0}
    real_judge_once = loop_mod.judge_once

    async def spy(*a, **k):
        calls["judge_once"] += 1
        return await real_judge_once(*a, **k)

    loop_mod.judge_once = spy
    providers_mod.get_decision_provider = decision_factory
    try:
        res = await implement_plan(bank, "run-6f2a", model=fake)
    finally:
        loop_mod.judge_once = real_judge_once
        providers_mod.get_decision_provider = _ORIG_GET_DECISION

    q = res.quality
    judge_prompts = [s for s in fake.seen if "QA CRITIC" in s]
    return {
        "label": label,
        "judge_once": calls["judge_once"],
        "fake_judge_turns": fake.judge_calls,  # cross-check: model turns tagged QA CRITIC
        "accepted": (q.accepted if q else None),
        "rounds": (q.rounds if q else 0),
        "final_score": (round(q.final_score, 3) if q else None),
        "scenarios": len(res.scenarios),
        "judge_prompt_chars": (max((len(s) for s in judge_prompts), default=0)),
    }


# --- Experiment B: TEV build_semantic_judge -----------------------------------------------------
def run_config_B(label: str, *, use_jev: bool, p_true: float = 0.8, n: int = 10) -> dict:
    fake_provider = FakeModelProvider(answer="yes")
    judge_mod.get_provider = lambda: fake_provider
    if use_jev:
        v = Verdict(value=(p_true >= 0.5), probs={"true": p_true}, confidence=0.9)
        providers_mod.get_decision_provider = lambda: FakeDecisionProvider(noul=v)
    else:
        providers_mod.get_decision_provider = lambda: None
    try:
        judge = judge_mod.build_semantic_judge()
        assert judge is not None, "build_semantic_judge returned None (provider not configured)"
        outputs = [judge(f"Is item {i} covered?", "some candidate text") for i in range(n)]
    finally:
        providers_mod.get_decision_provider = _ORIG_GET_DECISION
        judge_mod.get_provider = _ORIG_TEV_GET_PROVIDER

    expected = None if not use_jev else (p_true >= 0.5)
    correct = None if expected is None else all(o is expected for o in outputs)
    return {
        "label": label,
        "n": n,
        "llm_calls": len(fake_provider.prompts),
        "true_count": sum(1 for o in outputs if o),
        "expected_bool": expected,
        "correct": correct,
    }


# --- Deploy-safety smoke ------------------------------------------------------------------------
def smoke(label: str, *, backend: str | None, api_key: str | None) -> dict:
    # real (un-monkeypatched) registry reads the env each call
    providers_mod.get_decision_provider = _ORIG_GET_DECISION
    if backend is None:
        os.environ.pop("TPD_DECISION_BACKEND", None)
    else:
        os.environ["TPD_DECISION_BACKEND"] = backend
    if api_key is None:
        os.environ.pop("TYPESAFE_API_KEY", None)
    else:
        os.environ["TYPESAFE_API_KEY"] = api_key

    out = {"label": label, "app_built": False, "provider": None,
           "is_configured": None, "error": None}
    try:
        import main
        app = main.build_app("test_plan_definition")
        out["app_built"] = app is not None
        dp = providers_mod.get_decision_provider()
        out["provider"] = type(dp).__name__ if dp is not None else "None"
        out["is_configured"] = (dp.is_configured() if dp is not None else False)
    except Exception as exc:  # noqa: BLE001 — a smoke test reports failures, never raises
        out["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        os.environ.pop("TPD_DECISION_BACKEND", None)
        os.environ.pop("TYPESAFE_API_KEY", None)
    return out


# --- modeled latency/cost (vendor figures x measured call counts) -------------------------------
# docs/RESEARCH-typesafe-jev.md (TypeSafe's OWN claims, directional):
JEV_LAT_S = 0.150            # ~150ms point; vendor range 0.070-0.500s
LLM_LAT_S = 3.0              # conservative point; vendor LLM range 3-329s on structured tasks
JEV_RATE_IN = 0.042 / 1e6    # $/input-token, output free
LLM_RATE_IN_LO, LLM_RATE_IN_HI = 0.20 / 1e6, 10.0 / 1e6  # $/input-token (output extra, not modeled)


def modeled_deltas(avoided_judge_calls: int, jev_calls_added: int,
                   judge_prompt_chars: int, jev_state_chars: int) -> dict:
    judge_in_tok = judge_prompt_chars // 4  # ~4 chars/token, grounded in the measured prompt size
    jev_in_tok = jev_state_chars // 4
    lat_saved = avoided_judge_calls * LLM_LAT_S - jev_calls_added * JEV_LAT_S
    llm_cost_lo = avoided_judge_calls * judge_in_tok * LLM_RATE_IN_LO
    llm_cost_hi = avoided_judge_calls * judge_in_tok * LLM_RATE_IN_HI
    jev_cost = jev_calls_added * jev_in_tok * JEV_RATE_IN
    return {
        "judge_in_tok": judge_in_tok, "jev_in_tok": jev_in_tok,
        "lat_saved_point_s": round(lat_saved, 2),
        "lat_saved_range_s": (round(avoided_judge_calls * 3.0 - jev_calls_added * JEV_LAT_S, 2),
                              round(avoided_judge_calls * 329.0 - jev_calls_added * JEV_LAT_S, 2)),
        "cost_saved_in_only_usd": (round(llm_cost_lo - jev_cost, 8), round(llm_cost_hi - jev_cost, 8)),
    }


def _row(cells, widths):
    return " | ".join(str(c).ljust(w) for c, w in zip(cells, widths))


async def main_async() -> None:
    print("=" * 78)
    print("JEV CASCADE EXPERIMENT (offline; fakes stand in for JEV + LLM)")
    print("=" * 78)

    # Experiment A
    a_base = await run_config_A("A1 baseline OFF", lambda: None)
    rec = RecordingDecision(score=Verdict(value=0.92, probs=None, confidence=0.9))
    a_fast = await run_config_A("A2 JEV accept-fast", lambda: rec)
    a_fall = await run_config_A(
        "A3 JEV fallback", lambda: FakeDecisionProvider(score=Verdict(0.92, None, 0.4)))

    print("\n[Experiment A] assured loop — per implement_plan run "
          "(TPD_JUDGE_SAMPLES=production default 3)")
    w = [22, 12, 10, 8, 12, 10]
    print(_row(["config", "judge_once", "accepted", "rounds", "final_score", "scenarios"], w))
    print("-" * sum(w) + "-" * (len(w) * 3))
    for r in (a_base, a_fast, a_fall):
        print(_row([r["label"], r["judge_once"], r["accepted"], r["rounds"],
                    r["final_score"], r["scenarios"]], w))
    avoided = a_base["judge_once"] - a_fast["judge_once"]
    print(f"\nLLM judge calls avoided (accept-fast) = baseline {a_base['judge_once']} "
          f"- accept-fast {a_fast['judge_once']} = {avoided} per implement run")
    print(f"fallback path re-runs the full LLM judge ({a_fall['judge_once']} calls) "
          "AND spends 1 wasted JEV score call")
    print(f"(cross-check fake QA-CRITIC model turns: baseline={a_base['fake_judge_turns']}, "
          f"accept-fast={a_fast['fake_judge_turns']}, fallback={a_fall['fake_judge_turns']})")

    # Experiment B
    b_base = run_config_B("B1 baseline OFF", use_jev=False)
    b_jev_t = run_config_B("B2 JEV noul (P=0.8)", use_jev=True, p_true=0.8)
    b_jev_f = run_config_B("B3 JEV noul (P=0.2)", use_jev=True, p_true=0.2)

    print("\n[Experiment B] TEV build_semantic_judge — per batch of N yes/no judgements")
    wb = [22, 6, 12, 12, 14, 9]
    print(_row(["config", "N", "llm_calls", "true_count", "expected_bool", "correct"], wb))
    print("-" * sum(wb) + "-" * (len(wb) * 3))
    for r in (b_base, b_jev_t, b_jev_f):
        print(_row([r["label"], r["n"], r["llm_calls"], r["true_count"],
                    r["expected_bool"], r["correct"]], wb))
    per100 = (b_base["llm_calls"] - b_jev_t["llm_calls"]) * (100 // b_base["n"])
    print(f"\nLLM calls avoided per 100 judgements (JEV noul) = {per100}")

    # Deploy-safety smoke
    s_unset = smoke("unset (default OFF)", backend=None, api_key=None)
    s_jev = smoke("jev, no TYPESAFE_API_KEY", backend="jev", api_key=None)
    print("\n[Deploy-safety smoke] main.build_app('test_plan_definition')")
    ws = [26, 11, 16, 14, 8]
    print(_row(["config", "app_built", "provider", "is_configured", "error"], ws))
    print("-" * sum(ws) + "-" * (len(ws) * 3))
    for r in (s_unset, s_jev):
        print(_row([r["label"], r["app_built"], r["provider"], r["is_configured"],
                    r["error"] or "-"], ws))

    # Modeled latency/cost (label clearly)
    md = modeled_deltas(avoided_judge_calls=avoided, jev_calls_added=1,
                        judge_prompt_chars=a_base["judge_prompt_chars"],
                        jev_state_chars=(max((len(s) for s in rec.states), default=0)))
    print("\n[MODELED latency/cost] = vendor per-call figures x MEASURED call counts "
          "(NOT measured wall-clock)")
    print(f"  measured: judge prompt ~{a_base['judge_prompt_chars']} chars "
          f"(~{md['judge_in_tok']} in-tok); JEV state ~{max((len(s) for s in rec.states), default=0)}"
          f" chars (~{md['jev_in_tok']} in-tok)")
    print(f"  Experiment A accept-fast, per implement run: {avoided} LLM judge calls -> "
          "1 JEV score call")
    print(f"    latency saved (point: LLM 3.0s, JEV 0.150s) ~ {md['lat_saved_point_s']}s/run")
    print(f"    latency saved (vendor LLM range 3-329s)     ~ {md['lat_saved_range_s'][0]}s "
          f".. {md['lat_saved_range_s'][1]}s/run")
    lo, hi = md["cost_saved_in_only_usd"]
    print(f"    input-token cost saved (LLM $0.20-10/M in vs JEV $0.042/M in; LLM output extra, "
          f"not modeled) ~ ${lo:.6f} .. ${hi:.6f}/run")
    print(f"  TEV, per 100 judgements: {per100} LLM calls -> 0 (JEV noul), "
          "same per-call figures apply")
    print("\nDONE.")


if __name__ == "__main__":
    asyncio.run(main_async())
