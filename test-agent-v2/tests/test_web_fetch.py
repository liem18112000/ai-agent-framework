"""G3 external-web slice: WebFetcher, the Scope.follow_web gate, _fetchable, and the web"""

from __future__ import annotations

import httpx
import pytest

from common.extract import extract_issue_links
from common.memory import MemoryBank
from common.models import EXTERNAL_WEB, JIRA_ISSUE, Scope
from knowledge_gathering.loop import crawl
from knowledge_gathering.loop.crawl import _fetchable
from knowledge_gathering.loop.fetch import web
from knowledge_gathering.loop.fetch.base import NodeFetcher

BASE = "https://axonivy.atlassian.net"


def _mock_web_client(handler) -> httpx.AsyncClient:
    """A plain httpx client whose transport is faked — mirrors web._build_client's kwargs."""
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        timeout=web._TIMEOUT,
        follow_redirects=True,
        max_redirects=web._MAX_REDIRECTS,
    )


def _issue(key: str, urls: tuple[str, ...] = ()) -> dict:
    """A Jira issue whose description names external URLs (caught by the regex link source)."""
    text = "See " + " ".join(urls)
    return {
        "key": key,
        "fields": {
            "summary": f"Issue {key}",
            "description": {
                "type": "doc", "version": 1,
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
            },
        },
    }


class FakeClient:
    base_url = BASE

    def __init__(self, issues: dict):
        self.issues = issues

    async def get_issue(self, key: str):
        return self.issues[key]

    async def get_issue_remote_links(self, key: str):
        return []


async def test_web_fetch_200_html_returns_cited_leaf_note(monkeypatch):
    url = "https://example.com/spec"
    html = (
        "<html><head><title>eArchive Spec</title></head>"
        "<body><h1>Overview</h1><p>Hello <b>world</b></p>"
        "<script>var x = 1;</script></body></html>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == url
        return httpx.Response(200, html=html)

    monkeypatch.setattr(web, "_build_client", lambda: _mock_web_client(handler))
    links, note, text = await web.WebFetcher().fetch(None, "", url, Scope(follow_web=True))

    assert links == []
    assert note.type == EXTERNAL_WEB
    assert note.source_url == url
    assert note.title == "eArchive Spec"
    assert note.links == []
    assert note.synopsis == ""
    assert "Overview" in text and "world" in text
    assert "var x" not in text
    assert "<" not in text


async def test_web_fetch_title_falls_back_to_url(monkeypatch):
    url = "http://example.org/page"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, html="<p>no title here</p>")

    monkeypatch.setattr(web, "_build_client", lambda: _mock_web_client(handler))
    _, note, _ = await web.WebFetcher().fetch(None, "", url, Scope(follow_web=True))
    assert note.title == url


async def test_web_fetch_non_200_raises(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, html="nope")

    monkeypatch.setattr(web, "_build_client", lambda: _mock_web_client(handler))
    with pytest.raises(httpx.HTTPStatusError):
        await web.WebFetcher().fetch(None, "", "https://example.com/missing", Scope(follow_web=True))


async def test_web_fetch_disallowed_content_type_raises(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"%PDF-1.4", headers={"content-type": "application/pdf"})

    monkeypatch.setattr(web, "_build_client", lambda: _mock_web_client(handler))
    with pytest.raises(ValueError, match="content-type"):
        await web.WebFetcher().fetch(None, "", "https://example.com/x.pdf", Scope(follow_web=True))


async def test_web_fetch_oversize_raises(monkeypatch):
    monkeypatch.setattr(web, "_MAX_BYTES", 8)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, html="<p>" + "A" * 100 + "</p>")

    monkeypatch.setattr(web, "_build_client", lambda: _mock_web_client(handler))
    with pytest.raises(ValueError, match="exceeds"):
        await web.WebFetcher().fetch(None, "", "https://example.com/big", Scope(follow_web=True))


async def test_web_fetch_timeout_raises(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    monkeypatch.setattr(web, "_build_client", lambda: _mock_web_client(handler))
    with pytest.raises(httpx.TimeoutException):
        await web.WebFetcher().fetch(None, "", "https://example.com/slow", Scope(follow_web=True))


def test_http_and_https_both_registered():
    assert {"http", "https"}.issubset(NodeFetcher.registry)
    assert (
        type(NodeFetcher.registry["http"]).fetch is type(NodeFetcher.registry["https"]).fetch
    )


def test_scope_follows_external_web_only_when_enabled():
    assert Scope().follows(EXTERNAL_WEB) is False
    assert Scope(follow_web=True).follows(EXTERNAL_WEB) is True
    assert Scope().follows(JIRA_ISSUE) is True


def test_fetchable_http_gated_by_follow_web():
    assert _fetchable("https://example.com/x", Scope()) is False
    assert _fetchable("http://example.com/x", Scope()) is False
    assert _fetchable("https://example.com/x", Scope(follow_web=True)) is True
    assert _fetchable("jira:LUZ-1", Scope()) is True
    assert _fetchable("codegraph:ws/r", Scope()) is True
    assert _fetchable("bitbucket:ws/r/src/main/F.java", Scope()) is True


def test_external_web_in_scope_tracks_follow_web_flag():
    issue = _issue("LUZ-1", urls=("https://example.com/spec",))
    default = {r.canonical_url: r for r in extract_issue_links(issue, None, None, base_url=BASE, scope=Scope())}
    assert default["https://example.com/spec"].in_scope is False
    enabled = {
        r.canonical_url: r
        for r in extract_issue_links(issue, None, None, base_url=BASE, scope=Scope(follow_web=True))
    }
    assert enabled["https://example.com/spec"].in_scope is True


async def test_default_crawl_records_but_does_not_fetch_external_web(fake_bucket):
    issues = {"LUZ-1": _issue("LUZ-1", urls=("https://example.com/spec",))}
    result = await crawl(FakeClient(issues), MemoryBank(fake_bucket), "LUZ-1", depth=2, run_id="t")

    assert not any(n.type == EXTERNAL_WEB for n in result.notes)
    inv = {lr.canonical_url: lr for lr in result.inventory}
    assert inv["https://example.com/spec"].in_scope is False
    assert "https://example.com/spec" not in result.gaps


async def test_web_following_enabled_fetches_and_cites(fake_bucket, monkeypatch):
    url = "https://example.com/spec"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, html="<title>Spec</title><body><p>Zip import behavior</p></body>")

    monkeypatch.setattr(web, "_build_client", lambda: _mock_web_client(handler))
    issues = {"LUZ-1": _issue("LUZ-1", urls=(url,))}
    result = await crawl(FakeClient(issues), MemoryBank(fake_bucket), "LUZ-1",
                         depth=2, scope=Scope(follow_web=True), run_id="t")

    web_notes = [n for n in result.notes if n.type == EXTERNAL_WEB]
    assert len(web_notes) == 1
    n = web_notes[0]
    assert n.id == url and n.source_url == url
    assert n.synopsis
    assert not n.links


async def test_web_subbudget_caps_promotions(fake_bucket, monkeypatch):
    urls = tuple(f"https://example.com/p{i}" for i in range(5))
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, html="<title>P</title><body><p>body</p></body>")

    monkeypatch.setattr(web, "_build_client", lambda: _mock_web_client(handler))
    issues = {"LUZ-1": _issue("LUZ-1", urls=urls)}
    result = await crawl(FakeClient(issues), MemoryBank(fake_bucket), "LUZ-1",
                         depth=2, scope=Scope(follow_web=True, max_web=2), run_id="t")

    assert len([n for n in result.notes if n.type == EXTERNAL_WEB]) == 2
    assert len(calls) == 2
