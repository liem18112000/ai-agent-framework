"""M2 integration: drive Test Plan definition through the real A2A stack (multi-turn)."""

from __future__ import annotations

import json

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.utils import DEFAULT_RPC_URL
from conftest import FakeBucket, load_fixture_bucket
from starlette.applications import Starlette
from starlette.testclient import TestClient

from common.memory import MemoryBank
from common.models import Question
from test_plan_definition.a2a_card import AGENT_CARD
from test_plan_definition.executor import TestPlanDefinitionExecutor


def _gen(pack, rnd):
    """A fresh single OPEN question per round (so every round pauses for a human answer)."""
    specs = {
        "methodology": {"id": "Q-mth-1", "question": "Which methodology?",
                        "options": [{"label": "API", "implication": "x"},
                                    {"label": "E2E", "implication": "y"}],
                        "recommendation": "API"},
        "scope": {"id": "Q-sco-1", "question": "In scope?",
                  "options": [{"label": "In scope", "implication": "x"},
                              {"label": "Out of scope", "implication": "y"}],
                  "recommendation": "In scope"},
        "metrics": {"id": "Q-mtr-1", "question": "Passed means?",
                    "options": [{"label": "Accepted", "implication": "x"},
                                {"label": "End-state verified", "implication": "y"}],
                    "recommendation": "End-state verified"},
    }
    spec = specs.get(rnd)
    return [Question(round=rnd, **spec)] if spec else []


def _app(bucket=None):
    bank = MemoryBank(bucket if bucket is not None else load_fixture_bucket("pack_run-6f2a"))
    executor = TestPlanDefinitionExecutor(bank=bank, generator=_gen)
    handler = DefaultRequestHandler(
        agent_executor=executor, task_store=InMemoryTaskStore(), agent_card=AGENT_CARD)
    app = Starlette(routes=create_jsonrpc_routes(handler, DEFAULT_RPC_URL, enable_v0_3_compat=True))
    app.state.bank = bank
    return app


def _send(client, text, *, task_id=None, context_id="ctx-1"):
    msg = {"messageId": "m", "role": "user", "parts": [{"kind": "text", "text": text}],
           "contextId": context_id}
    if task_id:
        msg["taskId"] = task_id
    payload = {"jsonrpc": "2.0", "id": 1, "method": "message/send", "params": {"message": msg}}
    return client.post("/", json=payload).json()


def test_define_multiturn_pauses_then_confirms():
    app = _app()
    c = TestClient(app)

    r1 = _send(c, "define run-6f2a", context_id="ctx-1")
    s1 = json.dumps(r1)
    assert "Q-mth-1" in s1 and "methodology" in s1.lower()
    task_id = r1.get("result", {}).get("id") or r1.get("result", {}).get("taskId")

    _send(c, "Q-mth-1: API", task_id=task_id, context_id="ctx-1")
    _send(c, "Q-sco-1: In scope", task_id=task_id, context_id="ctx-1")
    r4 = _send(c, "Q-mtr-1: End-state verified", task_id=task_id, context_id="ctx-1")
    s4 = json.dumps(r4)
    assert "Plan definition complete" in s4 and "confirmed" in s4

    bank = app.state.bank
    plan = bank.get_json("memory/test-plan/run-6f2a/plan.json", None)
    assert plan and plan["status"] == "confirmed" and plan["methodology"] == ["api"]
    store = bank._bucket.store
    assert "memory/test-plan/run-6f2a/plan-brief.md" in store
    assert "memory/test-plan/run-6f2a/decisions.json" in store
    assert any(k.startswith("memory/runs/") and "plan-" in k for k in store)


def test_get_test_plan_helper_before_any_run():
    c = TestClient(_app())
    r = _send(c, "get-test-plan run-6f2a", context_id="ctx-ro")
    assert "No test plan yet" in json.dumps(r)


def test_define_empty_bank_says_run_gather_refine_first():
    c = TestClient(_app(bucket=FakeBucket()))
    r = _send(c, "define run-6f2a", context_id="ctx-x")
    assert "Nothing to plan" in json.dumps(r)


def test_bare_text_gets_help_not_a_crash():
    c = TestClient(_app())
    r = _send(c, "hello there", context_id="ctx-h")
    assert "test-plan-definition agent" in json.dumps(r)


def test_implement_after_confirm_generates_scenarios():
    app = _app()
    c = TestClient(app)
    r1 = _send(c, "define run-6f2a", context_id="ctx-1")
    task_id = r1.get("result", {}).get("id") or r1.get("result", {}).get("taskId")
    _send(c, "Q-mth-1: API", task_id=task_id, context_id="ctx-1")
    _send(c, "Q-sco-1: In scope", task_id=task_id, context_id="ctx-1")
    _send(c, "Q-mtr-1: End-state verified", task_id=task_id, context_id="ctx-1")

    ri = _send(c, "implement run-6f2a", context_id="ctx-impl")
    assert "Implement complete" in json.dumps(ri)

    rs = _send(c, "get-scenarios run-6f2a", context_id="ctx-ro2")
    assert "Test Scenarios" in json.dumps(rs)

    from test_plan_definition import memory as store
    assert store.read_scenarios(app.state.bank, "run-6f2a")


def test_implement_before_define_is_guarded():
    c = TestClient(_app())
    r = _send(c, "implement run-6f2a", context_id="ctx-noplan")
    assert "run define first" in json.dumps(r)
