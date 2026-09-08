"""Offline harness — drive the KGA executor in-process (no HTTP, no Cloud Run, no live network)."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.utils import DEFAULT_RPC_URL
from starlette.applications import Starlette
from starlette.testclient import TestClient

from common.memory import MemoryBank
from knowledge_gathering.a2a_card import AGENT_CARD
from knowledge_gathering.executor import KnowledgeGatheringExecutor
from tests.conftest import FakeBucket

_FIX = Path(__file__).parent / "fixtures" / "atlassian"

_TIER_MARKERS = [
    ("G2_hypothesize", "Hypothesized focus:"),
    ("B1_climb", "climbed to structural parent"),
    ("G0_self_seed", "Prior knowledge from memory"),
    ("G1_atlassian_search", "Atlassian search (seed was thin) surfaced"),
    ("G4_leads", "External-LLM leads"),
]


def derive_tiers(reply: str) -> list[str]:
    return [name for name, marker in _TIER_MARKERS if marker in reply]


class RecordedAtlassianClient:
    """Duck-typed AtlassianClient backed by recorded fixture JSON. Records every call for tool-use"""

    base_url = "https://axonivy.atlassian.net"

    def __init__(self, data: dict):
        self._issues = data.get("issues", {})
        self._remote = data.get("remote_links", {})
        self._pages = data.get("pages", {})
        self._jql = data.get("jql", {})
        self._cql = data.get("cql", {})
        self._dev = data.get("dev_status", {})
        self.calls: list[tuple] = []

    async def get_issue(self, key):
        self.calls.append(("get_issue", key))
        return self._issues[key]

    async def get_issue_remote_links(self, key):
        self.calls.append(("get_issue_remote_links", key))
        return self._remote.get(key, [])

    async def get_issue_dev_status(self, issue_id, data_type, application_type="bitbucket"):
        self.calls.append(("get_issue_dev_status", issue_id, data_type))
        return self._dev.get(str(issue_id), {})

    async def search_jql(self, jql, *, max_results=10):
        self.calls.append(("search_jql", jql))
        return self._jql.get(jql, [])

    async def search_cql(self, cql, *, limit=10):
        self.calls.append(("search_cql", cql))
        return self._cql.get(cql, [])

    async def get_page(self, page_id):
        self.calls.append(("get_page", page_id))
        return self._pages[page_id]


def load_atlassian_fixture(name: str) -> dict:
    return json.loads((_FIX / f"{name}.json").read_text(encoding="utf-8"))


def recorded_client(name: str) -> RecordedAtlassianClient:
    return RecordedAtlassianClient(load_atlassian_fixture(name))


@contextmanager
def env(flags: dict):
    """Temporarily set env flags (e.g. {'KGA_EXPLORE_LOOP': '1'}), restoring prior values after."""
    old = {k: os.environ.get(k) for k in flags}
    os.environ.update({k: str(v) for k, v in flags.items()})
    try:
        yield
    finally:
        for k, v in old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def _all_text(obj) -> str:
    """Concatenate every `text` value in the JSON-RPC response (status message + artifacts +"""
    out: list[str] = []

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                out.append(v) if k == "text" and isinstance(v, str) else walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    walk(obj)
    return "\n".join(out)


def _app(bank, client=None):
    ex = KnowledgeGatheringExecutor(bank=bank, client=client)
    handler = DefaultRequestHandler(
        agent_executor=ex, task_store=InMemoryTaskStore(), agent_card=AGENT_CARD)
    return Starlette(routes=create_jsonrpc_routes(handler, DEFAULT_RPC_URL, enable_v0_3_compat=True))


def _send(tc: TestClient, text: str, *, context_id: str | None = None) -> dict:
    msg = {"messageId": "m", "role": "user", "parts": [{"kind": "text", "text": text}]}
    if context_id:
        msg["contextId"] = context_id
    payload = {"jsonrpc": "2.0", "id": 1, "method": "message/send", "params": {"message": msg}}
    return tc.post("/", json=payload).json()


@dataclass
class RunTrace:
    """What a human reviews after a gather: the reply, the persisted pack, the tiers, the answer."""

    seed: str
    reply: str
    bank: MemoryBank
    context_id: str = ""
    client: RecordedAtlassianClient | None = None
    understanding: str = ""

    @property
    def node_ids(self) -> set[str]:
        graph, _ = self.bank.load_index()
        return set(graph.nodes.keys())

    @property
    def node_texts(self) -> list[str]:
        graph, _ = self.bank.load_index()
        return [f"{n.get('title', '')} {nid}" for nid, n in graph.nodes.items()]

    @property
    def tiers(self) -> list[str]:
        return derive_tiers(self.reply)

    @property
    def fetch_kinds(self) -> list[str]:
        return sorted({nid.split(":", 1)[0] for nid in self.node_ids})

    @property
    def tool_calls(self) -> list[str]:
        return [c[0] for c in self.client.calls] if self.client else []


def run_gather_offline(seed: str, *, client: RecordedAtlassianClient, bank: MemoryBank | None = None,
                       flags: dict | None = None, text: str | None = None,
                       context_id: str | None = None) -> RunTrace:
    """Drive one gather through the real executor with a recorded client. Returns a RunTrace whose"""
    bank = bank or MemoryBank(FakeBucket())
    context_id = context_id or f"eval-{seed}"
    with env(flags or {}):
        body = _send(TestClient(_app(bank, client)), text or f"gather {seed}", context_id=context_id)
    return RunTrace(seed=seed, reply=_all_text(body), bank=bank, context_id=context_id, client=client)


def run_refine_offline(bank: MemoryBank, ctx: str, *, seed: str = ""):
    """Run the refine interrogation to completion offline (heuristic answers, no LLM). Returns a"""
    import asyncio

    from common.interrogate.loop import refine
    return asyncio.run(refine(bank, ctx, seed=seed or ctx))
