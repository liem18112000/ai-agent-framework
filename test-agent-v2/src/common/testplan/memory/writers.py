"""Persist Test-Plan artifacts to the shared memory bank under memory/test-plan/<ctx>/."""

from __future__ import annotations

from dataclasses import asdict

from common.memory.bank import ROOT, _slug
from common.memory.serialize import _from
from common.models import Answer, Question
from common.testplan.memory.render import (
    render_plan_md,
    render_run_log_md,
    render_scenarios_md,
)
from common.testplan.models import (
    PlanDecision,
    TestData,
    TestPlan,
    TestPlanRun,
    TestScenario,
    TestStep,
)


def _dir(context_id: str) -> str:
    return f"{ROOT}/test-plan/{_slug(context_id)}"


def write_questions(bank, context_id: str, questions: list[Question]) -> str:
    return bank.put_json(f"{_dir(context_id)}/questions.json", [asdict(q) for q in questions])


def read_questions(bank, context_id: str) -> list[Question]:
    return [_from(Question, d) for d in bank.get_json(f"{_dir(context_id)}/questions.json", [])]


def write_answers(bank, context_id: str, answers: list[Answer]) -> str:
    """Append-only answer log."""
    path = f"{_dir(context_id)}/answers.json"
    return bank.put_json(path, bank.get_json(path, []) + [asdict(a) for a in answers])


def read_answers(bank, context_id: str) -> list[Answer]:
    return [_from(Answer, d) for d in bank.get_json(f"{_dir(context_id)}/answers.json", [])]


def write_decisions(bank, context_id: str, decisions: list[PlanDecision]) -> str:
    return bank.put_json(f"{_dir(context_id)}/decisions.json", [asdict(d) for d in decisions])


def read_decisions(bank, context_id: str) -> list[PlanDecision]:
    return [_from(PlanDecision, d) for d in bank.get_json(f"{_dir(context_id)}/decisions.json", [])]


def write_plan(bank, plan: TestPlan) -> str:
    bank.put_json(f"{_dir(plan.context_id)}/plan.json", asdict(plan))
    return bank.put_text(f"{_dir(plan.context_id)}/plan.md", render_plan_md(plan))


def read_plan(bank, context_id: str) -> TestPlan | None:
    d = bank.get_json(f"{_dir(context_id)}/plan.json", None)
    return _from(TestPlan, d) if d else None


def write_plan_brief(bank, context_id: str, md: str) -> str:
    return bank.put_text(f"{_dir(context_id)}/plan-brief.md", md)


def read_plan_brief(bank, context_id: str) -> str | None:
    return bank.get_text(f"{_dir(context_id)}/plan-brief.md")


def write_test_data(bank, context_id: str, test_data: list[TestData]) -> str:
    return bank.put_json(f"{_dir(context_id)}/test-data.json", [asdict(d) for d in test_data])


def read_test_data(bank, context_id: str) -> list[TestData]:
    return [_from(TestData, d) for d in bank.get_json(f"{_dir(context_id)}/test-data.json", [])]


def write_scenarios(bank, context_id: str, scenarios: list[TestScenario],
                    steps: list[TestStep] | None = None) -> str:
    bank.put_json(f"{_dir(context_id)}/scenarios.json", [asdict(s) for s in scenarios])
    return bank.put_text(f"{_dir(context_id)}/scenarios.md",
                         render_scenarios_md(context_id, scenarios, steps or []))


def read_scenarios(bank, context_id: str) -> list[TestScenario]:
    return [_from(TestScenario, d) for d in bank.get_json(f"{_dir(context_id)}/scenarios.json", [])]


def read_scenarios_md(bank, context_id: str) -> str | None:
    return bank.get_text(f"{_dir(context_id)}/scenarios.md")


def write_steps(bank, context_id: str, steps: list[TestStep]) -> str:
    return bank.put_json(f"{_dir(context_id)}/steps.json", [asdict(s) for s in steps])


def read_steps(bank, context_id: str) -> list[TestStep]:
    return [_from(TestStep, d) for d in bank.get_json(f"{_dir(context_id)}/steps.json", [])]


def write_feature(bank, context_id: str, name: str, text: str) -> str:
    return bank.put_text(f"{_dir(context_id)}/features/{_slug(name)}.feature", text)


def read_feature(bank, context_id: str, name: str) -> str | None:
    return bank.get_text(f"{_dir(context_id)}/features/{_slug(name)}.feature")


def write_plan_state(bank, context_id: str, state: dict) -> str:
    return bank.put_json(f"{_dir(context_id)}/state.json", state)


def read_plan_state(bank, context_id: str) -> dict:
    return bank.get_json(f"{_dir(context_id)}/state.json", {})


def link_session(bank, a2a_context_id: str, pack_context_id: str) -> str:
    return bank.put_json(f"{ROOT}/test-plan/_sessions/{_slug(a2a_context_id)}.json",
                         {"pack_context_id": pack_context_id})


def resolve_session(bank, a2a_context_id: str) -> str | None:
    d = bank.get_json(f"{ROOT}/test-plan/_sessions/{_slug(a2a_context_id)}.json", None)
    return d.get("pack_context_id") if d else None


def append_plan_run_log(bank, run: TestPlanRun) -> str:
    path = f"{ROOT}/runs/{_slug(run.started) or run.run_id}_plan-{run.run_id}.md"
    return bank.put_text(path, render_run_log_md(run))
