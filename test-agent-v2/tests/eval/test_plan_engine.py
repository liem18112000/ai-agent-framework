"""Tests for the TPD evaluation surface — the plan_engine + the A2A executor's evaluate_plan.

Drives gather -> refine -> define -> implement offline (harness), then scores the persisted plan+suite
through the runtime engine (which reads the artifacts from the bank as dicts, NOT from the harness),
and drives the executor end-to-end over the real A2A stack.
"""

from __future__ import annotations

import json

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.utils import DEFAULT_RPC_URL
from starlette.applications import Starlette
from starlette.testclient import TestClient

from test_evaluation.a2a_card import AGENT_CARD
from test_evaluation.executor import TestEvaluationExecutor
from test_evaluation.models import PlanEvalCase
from test_evaluation.plan_engine import evaluate_plan
from tests.eval.harness_tpd import run_plan_offline


# --- engine (reads the persisted plan+suite from the bank, independent of the harness) --- #
def test_evaluate_plan_scores_a_clean_suite():
    t = run_plan_offline("LUZ-501", "eval_rich")
    case = PlanEvalCase.from_dict({
        "seed": "LUZ-501",
        "in_scope_ids": ["jira:LUZ-501", "jira:LUZ-502", "jira:LUZ-503"],
        "behaviours": [{"id": "jira:LUZ-501", "expected_partitions": ["happy", "negative", "boundary", "error"]},
                       {"id": "jira:LUZ-502", "expected_partitions": ["happy"]},
                       {"id": "jira:LUZ-503", "expected_partitions": ["happy"]}],
    })
    r = evaluate_plan(t.bank, t.ctx, case)
    assert r.scope.leaked == [] and r.scope.precision == 1.0     # scoped node is in the golden set
    assert r.coverage.ac_recall == 1.0                            # every behaviour has scenarios
    assert r.rubrics.cites_only_real_ids.passed                   # brief cites only in-pack ids
    assert 0.0 <= r.tps <= 1.0 and r.components.trajectory == 1.0  # neutral trajectory at runtime


def test_evaluate_plan_flags_a_scope_leak():
    """A must_not_scope id that the plan scoped is a hard fail — the define-brief-scoping guard."""
    t = run_plan_offline("LUZ-701", "eval_bleed")
    # force the failure mode: mark the node the plan DID scope as must-not-scope.
    scoped = t.plan.scope[0]
    case = PlanEvalCase.from_dict({"seed": "LUZ-701", "in_scope_ids": ["jira:LUZ-702"],
                                   "must_not_scope_ids": [scoped]})
    r = evaluate_plan(t.bank, t.ctx, case)
    assert r.scope.leaked == [scoped]                             # the engine surfaces the bleed


# --- A2A executor --- #
def _app(bank):
    ex = TestEvaluationExecutor(bank=bank)
    handler = DefaultRequestHandler(agent_executor=ex, task_store=InMemoryTaskStore(),
                                    agent_card=AGENT_CARD)
    return Starlette(routes=create_jsonrpc_routes(handler, DEFAULT_RPC_URL, enable_v0_3_compat=True))


def _send(tc, text, ctx):
    payload = {"jsonrpc": "2.0", "id": 1, "method": "message/send",
               "params": {"message": {"messageId": "m", "role": "user", "contextId": ctx,
                                      "parts": [{"kind": "text", "text": text}]}}}
    return tc.post("/", json=payload).json()


def test_executor_evaluate_plan_over_a2a():
    t = run_plan_offline("LUZ-501", "eval_rich")
    body = json.dumps(_send(TestClient(_app(t.bank)), f"evaluate plan {t.ctx}", t.ctx))
    assert "Test-Plan Score" in body and "Components:" in body
