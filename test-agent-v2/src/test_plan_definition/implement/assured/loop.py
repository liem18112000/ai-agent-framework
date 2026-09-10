"""P4 — the Assured Generation Loop (§3.1 / §3.4): generate → judge → gate → reflect → regenerate.

ALWAYS on — this is the implement scenario-generation path (``implement_plan`` calls it unconditionally;
the old ``TPD_ASSURED`` opt-in gate is gone). Bounded by ``TPD_ASSURED_MAX_ITERS`` (default 2). NOTE:
this trades away I3 (the 1-LLM-call default) — each round is generate + judge, so the worst case is
2·iters serial Vertex calls; keep ``TPD_ASSURED_MAX_ITERS=1`` in a latency-sensitive deployment to stay
clear of the Cloud-Run liveness/request timeout the three-serial-call bug once hit. State is persisted
per ``context_id`` so a handler killed mid-loop RESUMES with its accumulated reflections + remaining
budget rather than restarting from scratch.

We do NOT have real execution yet (P1–P3), so 'measure' here is the LLM-as-judge rubric score, not
coverage/flakiness/mutation — the gate is honest about that. The human Yes/No gate is unchanged; this
loop only attaches a quality signal and self-repairs before it.

This is the ENGINE; ``AssuredScenarioAgent`` (agent.py) is the ADK ``BaseAgent`` face onto it.
``implement_plan`` calls ``run_assured_scenarios`` inline (it needs the scenarios back mid-pipeline);
the agent reconstructs its inputs from the bank and reports the same loop as an observable event.
"""

from __future__ import annotations

import contextlib
import os
from dataclasses import asdict

from common.testplan import memory as store
from common.testplan.models import AssuredReport, PlanPack, TestData, TestPlan, TestScenario
from test_plan_definition.monitoring import get_logger

log = get_logger("implement.assured")

_DEFAULT_MAX_ITERS = 2
_DEFAULT_THRESHOLD = 0.7
_MAX_ISSUES = 5


async def run_assured_scenarios(
    bank, context_id: str, plan: TestPlan, plan_pack: PlanPack, test_data: list[TestData], *,
    now: str = "", model=None,
) -> tuple[list[TestScenario], AssuredReport]:
    """Run the bounded assured loop and return the best scenario set + its quality report."""
    from common.adk import agent_model
    from common.testplan.llm.adk import build_generator_agent, run_json_agent
    from common.testplan.llm.prompts import judge_scenarios_prompt, pack_block
    from common.testplan.llm.schemas import JudgeVerdict
    from test_plan_definition.implement.generate.llm import claude_scenarios
    from test_plan_definition.implement.generate.scenarios import heuristic_scenarios

    # env-configured bounds (fall back to the defaults on a malformed value)
    max_iters, threshold = _DEFAULT_MAX_ITERS, _DEFAULT_THRESHOLD
    with contextlib.suppress(ValueError):
        max_iters = max(1, int(os.environ.get("TPD_ASSURED_MAX_ITERS", _DEFAULT_MAX_ITERS)))
    with contextlib.suppress(ValueError):
        threshold = float(os.environ.get("TPD_ASSURED_THRESHOLD", _DEFAULT_THRESHOLD))
    saved = store.read_assured_state(bank, context_id)
    # resume only a genuinely interrupted pass: some rounds done, not accepted, budget left
    done_rounds = len(saved.get("iterations", []))
    resume = bool(saved) and not saved.get("accepted") and 0 < done_rounds < max_iters
    history: list[dict] = list(saved.get("iterations", [])) if resume else []
    reflections: list[str] = list(saved.get("reflections", [])) if resume else []

    best_scenarios: list[TestScenario] = []
    best_score = -1.0
    best_verdict = None

    # The P4 LLM-as-judge model — its own smaller max_tokens (the verdict is short → cheap per round),
    # resolved once (the injected/configured model is stable across rounds). None → no judge signal.
    judge_model = model or agent_model(max_tokens=1500)

    for _ in range(len(history), max_iters):
        scenarios = await claude_scenarios(plan, plan_pack, test_data, now=now, model=model,
                                           reflections=reflections)
        if not scenarios:  # generation unconfigured/invalid → degrade, best-effort (never raise)
            scenarios = heuristic_scenarios(plan, plan_pack, test_data, now=now)

        # P4 LLM-as-judge (§3.4), inlined (sole caller): the stable pack is the agent's cached system
        # instruction and the scenarios-to-critique are the user turn; None (unconfigured/invalid
        # output) means no signal to gate on — the loop stops with a single unscored pass.
        verdict = None
        if judge_model is not None:
            summary = plan_pack.summary_text()
            judge = build_generator_agent(name="tpd_scenario_judge", system=pack_block(summary),
                                          output_schema=JudgeVerdict, output_key="tpd_verdict",
                                          model=judge_model)
            data = await run_json_agent(judge, output_key="tpd_verdict", user=judge_scenarios_prompt(
                plan, summary, scenarios, include_context=False))
            if data:
                verdict = JudgeVerdict(**data)
            else:
                log.warning("no verdict from judge; scenarios kept unscored")

        if verdict is None:  # no judge signal → nothing to gate on; stop with what we have
            best_scenarios = best_scenarios or scenarios
            note = "no judge configured — single unscored pass"
            log.info("assured: %s", note)
            report = AssuredReport(iterations=history, final_score=0.0, threshold=threshold,
                                   accepted=False, reflections=reflections, note=note)
            _persist(bank, context_id, report)
            return best_scenarios, report

        score = verdict.score()
        accepted = score >= threshold
        history.append({"iter": len(history) + 1, "score": round(score, 3), "accepted": accepted,
                        "issues": verdict.issues[:_MAX_ISSUES]})
        if score > best_score:
            best_score, best_scenarios, best_verdict = score, scenarios, verdict

        report = AssuredReport(
            iterations=history, final_score=round(best_score, 3), threshold=threshold,
            accepted=accepted, issues=(best_verdict.issues if best_verdict else []),
            reflections=reflections)
        _persist(bank, context_id, report)  # after each round → resumable across a Cloud-Run kill

        log.info("assured round %d: score=%.3f threshold=%.2f accepted=%s",
                 len(history), score, threshold, accepted)
        if accepted:
            report.note = f"accepted at round {len(history)} (score {score:.2f} ≥ {threshold:.2f})"
            _persist(bank, context_id, report)
            return best_scenarios, report

        # REFLECT — carry the judge's imperative fixes into the next generation (dedup, ordered).
        reflections = list(dict.fromkeys(reflections + verdict.reflections))

    note = (f"best {best_score:.2f} < {threshold:.2f} after {len(history)} rounds — "
            "surfaced for human review")
    report = AssuredReport(
        iterations=history, final_score=round(max(best_score, 0.0), 3), threshold=threshold,
        accepted=False, issues=(best_verdict.issues if best_verdict else []),
        reflections=reflections, note=note)
    _persist(bank, context_id, report)
    log.info("assured: %s", note)
    return best_scenarios, report


def _persist(bank, context_id: str, report: AssuredReport) -> None:
    """Best-effort GCS checkpoint of the loop state (the resume source). Never breaks the loop."""
    try:
        store.write_assured_state(bank, context_id, asdict(report))
    except Exception as exc:  # noqa: BLE001 — persistence is best-effort
        log.warning("assured: state checkpoint skipped (%s)", exc)
