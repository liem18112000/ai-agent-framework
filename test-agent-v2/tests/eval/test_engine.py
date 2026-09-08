"""Tests for the test_evaluation agent surface — the engine + the A2A executor."""

from __future__ import annotations

import json

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.utils import DEFAULT_RPC_URL
from starlette.applications import Starlette
from starlette.testclient import TestClient

from test_evaluation.a2a_card import AGENT_CARD
from test_evaluation.engine import evaluate_pack
from test_evaluation.executor import TestEvaluationExecutor
from test_evaluation.models import EvalCase
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


def test_executor_evaluate_over_a2a():
    bank = _refined("LUZ-501", "eval_rich", "LUZ-501")
    body = json.dumps(_send(TestClient(_app(bank)), "evaluate LUZ-501", "LUZ-501"))
    assert "Pack Quality Score for LUZ-501" in body and "Components:" in body


def test_executor_needs_a_context_id():
    body = json.dumps(_send(TestClient(_app(None)), "evaluate", "")).lower()
    assert "context id" in body or "memory bank unavailable" in body
