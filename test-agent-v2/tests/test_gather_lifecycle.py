"""GatherAgent lifecycle: it closes the httpx client it built (M4) and degrades — never 500s — when
the crawl/persist step fails (M6). Driven through the real ADK Runner via the shared harness."""

from __future__ import annotations

from tests.conftest import drive_gather_agent, fake_model


class RecordingClient:
    """Minimal Atlassian client for a one-node gather that also records `aclose()`."""

    base_url = "https://x.atlassian.net"

    def __init__(self) -> None:
        self.closed = False

    async def get_issue(self, key):
        return {"id": "1", "fields": {
            "summary": "Export fails", "description": {"type": "doc", "version": 1, "content": []},
            "issuelinks": [], "subtasks": [], "labels": [], "components": []}}

    async def get_issue_remote_links(self, key):
        return []

    async def search_jql(self, jql, *, max_results=10):
        return []

    async def search_cql(self, cql, *, limit=10):
        return []

    async def aclose(self):
        self.closed = True


async def test_gather_closes_the_client_it_built(monkeypatch):
    client = RecordingClient()
    reply, _ = await drive_gather_agent("LUZ-1", monkeypatch, client=client,
                                        hyp_model=fake_model("{}"), leads_model=fake_model("{}"))
    assert "Gather complete" in reply
    assert client.closed is True


async def test_gather_degrades_and_still_closes_when_crawl_fails(monkeypatch):
    import knowledge_gathering.gather.agent as ga

    async def _boom(*a, **k):
        raise RuntimeError("index CAS retries exhausted")

    monkeypatch.setattr(ga, "crawl", _boom)
    client = RecordingClient()
    reply, _ = await drive_gather_agent("LUZ-1", monkeypatch, client=client,
                                        hyp_model=fake_model("{}"), leads_model=fake_model("{}"))
    assert "could not complete" in reply.lower()   # M6: degraded reply, not an exception
    assert client.closed is True                   # M4: finally still releases the client
