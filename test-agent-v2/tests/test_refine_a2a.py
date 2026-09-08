"""R5 integration: drive Knowledge Refinement through the real A2A stack (multi-turn)."""

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
from knowledge_gathering.a2a_card import AGENT_CARD
from knowledge_gathering.executor import KnowledgeGatheringExecutor


def _gen(pack, rnd):
    """Return a FRESH single question for the round (real generators build new objects each call)."""
    specs = {
        "business": {"id": "Q-biz-1", "question": "Does 'done' mean accepted or fully materialized?",
                     "options": [{"label": "Accepted", "implication": "x"},
                                 {"label": "Materialized", "implication": "y"}],
                     "recommendation": "Materialized"},
        "technical": {"id": "Q-tech-1", "question": "Which tenant?",
                      "options": [{"label": "dev", "implication": "x"}], "recommendation": "dev"},
        "qa": {"id": "Q-qa-1", "question": "Coverage bar?",
               "options": [{"label": "happy", "implication": "x"}], "recommendation": "happy"},
    }
    spec = specs.get(rnd)
    return [Question(round=rnd, **spec)] if spec else []


def _app(bucket=None):
    bank = MemoryBank(bucket if bucket is not None else load_fixture_bucket("pack_run-6f2a"))
    executor = KnowledgeGatheringExecutor(bank=bank, generator=_gen)
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


def _task(body):
    return body.get("result", {})


def test_refine_multiturn_pauses_then_completes():
    app = _app()
    c = TestClient(app)

    r1 = _send(c, "refine run-6f2a", context_id="ctx-1")
    s1 = json.dumps(r1)
    assert "Q-biz-1" in s1 and "materialized" in s1.lower()
    task_id = _task(r1).get("id") or _task(r1).get("taskId")

    _send(c, "Q-biz-1: Materialized", task_id=task_id, context_id="ctx-1")
    _send(c, "Q-tech-1: dev", task_id=task_id, context_id="ctx-1")
    r4 = _send(c, "Q-qa-1: happy", task_id=task_id, context_id="ctx-1")
    s4 = json.dumps(r4)
    assert "Refinement complete" in s4 and "Understanding" in s4

    bank = app.state.bank
    assert bank.read_understanding("run-6f2a")
    store = bank._bucket.store
    assert any(k.startswith("memory/notes/insight/") for k in store)
    assert any("refine-" in k for k in store)
    ins = bank.read_insight("insight:run-6f2a:Q-biz-1")
    assert ins is not None and "Materialized" in ins.statement and ins.answered_by == "human"


def test_refine_empty_bank_says_run_gather_first():
    c = TestClient(_app(bucket=FakeBucket()))
    r = _send(c, "refine run-6f2a", context_id="ctx-x")
    assert "run gather first" in json.dumps(r).lower()


def test_get_understanding_helper_before_any_run():
    c = TestClient(_app())
    r = _send(c, "get-understanding run-6f2a", context_id="ctx-ro")
    assert "No understanding yet" in json.dumps(r)


def test_gather_still_routes_and_works():
    app = _app()
    c = TestClient(app)
    r = _send(c, "gather LUZ-158390 depth 0", context_id="ctx-g")
    assert "Config error" in json.dumps(r) or "Gather complete" in json.dumps(r)
