"""M4 integration: drive the crawl through the real A2A stack via message/send."""

from __future__ import annotations

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.utils import DEFAULT_RPC_URL
from google.api_core.exceptions import PreconditionFailed
from starlette.applications import Starlette
from starlette.testclient import TestClient

from common.memory import MemoryBank
from knowledge_gathering.a2a_card import AGENT_CARD
from knowledge_gathering.executor import KnowledgeGatheringExecutor


# --- minimal fakes (self-contained) --- #
class _Blob:
    def __init__(self, b, n):
        self._b, self.name = b, n

    @property
    def generation(self):
        return self._b.gens.get(self.name, 0)

    def download_as_text(self):
        return self._b.store[self.name]

    def upload_from_string(self, data, content_type=None, if_generation_match=None):
        cur = self._b.gens.get(self.name, 0)
        if if_generation_match is not None and if_generation_match != cur:
            raise PreconditionFailed("gen")
        self._b.store[self.name] = data
        self._b.gens[self.name] = cur + 1


class _Bucket:
    def __init__(self):
        self.store, self.gens = {}, {}

    def blob(self, n):
        return _Blob(self, n)

    def get_blob(self, n):
        return _Blob(self, n) if n in self.store else None


class _Client:
    base_url = "https://axonivy.atlassian.net"

    def __init__(self, issues):
        self.issues = issues

    async def get_issue(self, key):
        return self.issues[key]

    async def get_issue_remote_links(self, key):
        return []


def _issue(key, links_to=()):
    return {
        "key": key,
        "fields": {
            "summary": f"Issue {key}",
            "description": {"type": "doc", "version": 1, "content": []},
            "issuelinks": [{"type": {"name": "R"}, "outwardIssue": {"key": lk}} for lk in links_to],
        },
    }


def _app():
    issues = {"LUZ-1": _issue("LUZ-1", ["LUZ-2"]), "LUZ-2": _issue("LUZ-2")}
    executor = KnowledgeGatheringExecutor(client=_Client(issues), bank=MemoryBank(_Bucket()))
    handler = DefaultRequestHandler(
        agent_executor=executor, task_store=InMemoryTaskStore(), agent_card=AGENT_CARD
    )
    return Starlette(routes=create_jsonrpc_routes(handler, DEFAULT_RPC_URL, enable_v0_3_compat=True))


def _send(client, text):
    payload = {
        "jsonrpc": "2.0", "id": 1, "method": "message/send",
        "params": {"message": {"messageId": "m1", "role": "user",
                               "parts": [{"kind": "text", "text": text}]}},
    }
    return client.post("/", json=payload).json()


def test_gather_over_a2a():
    c = TestClient(_app())
    body = _send(c, "gather LUZ-1 depth 1")
    text = str(body)
    assert "2 nodes" in text
    assert "jira:LUZ-1" in text and "jira:LUZ-2" in text


def test_missing_seed_replies_helpfully():
    c = TestClient(_app())
    body = _send(c, "hello there")
    assert "Provide a seed" in str(body)
