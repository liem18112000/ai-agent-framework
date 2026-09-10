"""P4 — the Assured Generation Loop (§3.1 / §3.4): generate → judge → gate → reflect → regenerate.

Opt-in behind ``TPD_ASSURED`` (default OFF → ``implement_plan`` stays the I3 single-call path).
Bounded by ``TPD_ASSURED_MAX_ITERS`` (default 2 — keeps the worst-case sequential Vertex calls at
2·iters ≈ the already-accepted ``detail``=3 order, and off the Cloud-Run liveness/request timeout the
three-serial-call bug once hit). State is persisted per ``context_id`` so a handler killed mid-loop
RESUMES with its accumulated reflections + remaining budget rather than restarting from scratch.

We do NOT have real execution yet (P1–P3), so 'measure' here is the LLM-as-judge rubric score, not
coverage/flakiness/mutation — the gate is honest about that. The human Yes/No gate is unchanged; this
loop only attaches a quality signal and self-repairs before it.
"""

from __future__ import annotations

import os

from common.testplan import memory as store
from common.testplan.models import AssuredReport, PlanPack, TestData, TestPlan, TestScenario
from test_plan_definition.implement.generate.scenarios import heuristic_scenarios
from test_plan_definition.monitoring import get_logger

log = get_logger("implement.assured")

_DEFAULT_MAX_ITERS = 2
_DEFAULT_THRESHOLD = 0.7
_MAX_ISSUES = 5


def assured_enabled(assured: bool = False) -> bool:
    """The opt-in gate: an explicit ``assured=True`` (tests) or ``TPD_ASSURED`` in the environment."""
    return assured or bool(os.environ.get("TPD_ASSURED"))


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _resumable(saved: dict, max_iters: int) -> bool:
    """Resume only a genuinely interrupted pass: some rounds done, not yet accepted, budget left.
    A completed (accepted, or exhausted) prior pass means the client re-invoked implement → fresh."""
    done = len(saved.get("iterations", []))
    return bool(saved) and not saved.get("accepted") and 0 < done < max_iters


async def run_assured_scenarios(
    bank, context_id: str, plan: TestPlan, plan_pack: PlanPack, test_data: list[TestData], *,
    now: str = "", model=None,
) -> tuple[list[TestScenario], AssuredReport]:
    """Run the bounded assured loop and return the best scenario set + its quality report."""
    from test_plan_definition.implement.generate.llm import claude_judge_scenarios, claude_scenarios

    max_iters, threshold = _env_int("TPD_ASSURED_MAX_ITERS", _DEFAULT_MAX_ITERS), _env_float(
        "TPD_ASSURED_THRESHOLD", _DEFAULT_THRESHOLD)
    saved = store.read_assured_state(bank, context_id)
    resume = _resumable(saved, max_iters)
    history: list[dict] = list(saved.get("iterations", [])) if resume else []
    reflections: list[str] = list(saved.get("reflections", [])) if resume else []

    best_scenarios: list[TestScenario] = []
    best_score = -1.0
    best_verdict = None

    for _ in range(len(history), max_iters):
        scenarios = await claude_scenarios(plan, plan_pack, test_data, now=now, model=model,
                                           reflections=reflections)
        if not scenarios:  # generation unconfigured/invalid → degrade, best-effort (never raise)
            scenarios = heuristic_scenarios(plan, plan_pack, test_data, now=now)

        verdict = await claude_judge_scenarios(plan, plan_pack, scenarios, model=model)
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
    from dataclasses import asdict

    try:
        store.write_assured_state(bank, context_id, asdict(report))
    except Exception as exc:  # noqa: BLE001 — persistence is best-effort
        log.warning("assured: state checkpoint skipped (%s)", exc)
