"""Offline harness — drive the ADK KGA agent in-process (no HTTP, no Cloud Run, no live network)."""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from common.memory import MemoryBank
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
    """Duck-typed AtlassianClient backed by recorded fixture JSON; records every call for tool-use asserts."""

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


def _run_sync(coro):
    """Run a coroutine to completion whether or not the caller already has a running event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(1) as ex:
        return ex.submit(lambda: asyncio.run(coro)).result()


async def _adk_gather(text: str, context_id: str, client, bank: MemoryBank) -> str:
    """Drive the ADK KGA router through a Runner with session_id == context_id; return the reply text."""
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    import knowledge_gathering.agents.gather_agent as ga
    from knowledge_gathering.agent import build_root_agent

    with patch.object(ga, "build_client", lambda: client), \
         patch.object(ga, "build_bank", lambda: bank), \
         patch("knowledge_gathering.agent.build_bank", lambda: bank), \
         patch("common.adk.interrogation.build_bank", lambda: bank), \
         patch("common.adk.tools.build_bank", lambda: bank):
        svc = InMemorySessionService()
        await svc.create_session(app_name="kga", user_id="u", session_id=context_id)
        runner = Runner(app_name="kga", agent=build_root_agent(), session_service=svc)
        out: list[str] = []
        async for ev in runner.run_async(
            user_id="u", session_id=context_id,
            new_message=types.Content(role="user", parts=[types.Part(text=text)]),
        ):
            c = getattr(ev, "content", None)
            for p in getattr(c, "parts", None) or []:
                if getattr(p, "text", None) and getattr(c, "role", None) != "user":
                    out.append(p.text)
        return " ".join(out)


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
    """Drive one gather through the ADK KGA agent with a recorded client. Returns a RunTrace."""
    bank = bank or MemoryBank(FakeBucket())
    context_id = context_id or f"eval-{seed}"
    with env(flags or {}):
        reply = _run_sync(_adk_gather(text or f"gather {seed}", context_id, client, bank))
    return RunTrace(seed=seed, reply=reply, bank=bank, context_id=context_id, client=client)


def run_refine_offline(bank: MemoryBank, ctx: str, *, seed: str = ""):
    """Run the refine interrogation to completion offline (heuristic answers, no LLM)."""
    from common.interrogate.loop import refine
    return _run_sync(refine(bank, ctx, seed=seed or ctx))
