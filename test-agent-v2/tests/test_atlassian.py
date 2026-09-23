"""M1 tests: read-only Atlassian client + bounded retry (1s/2s/4s)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from common.atlassian import RETRY_BACKOFFS, AtlassianClient

FIX = Path(__file__).parent / "fixtures"


def _load(name: str):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def _client(handler, **kw) -> AtlassianClient:
    transport = httpx.MockTransport(handler)
    return AtlassianClient(
        "https://example.atlassian.net",
        "user@example.com",
        "token",
        client=httpx.AsyncClient(transport=transport),
        **kw,
    )


def test_backoffs_are_1_2_4():
    assert RETRY_BACKOFFS == (1.0, 2.0, 4.0)


async def test_get_issue_returns_fixture():
    issue = _load("LUZ-158390.issue.json")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/rest/api/3/issue/LUZ-158390"
        assert (
            request.url.params["fields"]
            == "summary,description,comment,issuelinks,attachment,parent,subtasks,labels,components"
        )
        return httpx.Response(200, json=issue)

    c = _client(handler)
    got = await c.get_issue("LUZ-158390")
    assert got["key"] == "LUZ-158390"
    assert got["fields"]["summary"].startswith("[eArchive]")
    await c.aclose()


async def test_get_issue_dev_status_hits_dev_panel_api():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/rest/dev-status/1.0/issue/detail"
        assert request.url.params["issueId"] == "10042"
        assert request.url.params["applicationType"] == "bitbucket"
        assert request.url.params["dataType"] == "pullrequest"
        return httpx.Response(200, json={"detail": [{"pullRequests": []}], "errors": []})

    c = _client(handler)
    got = await c.get_issue_dev_status("10042", "pullrequest")
    assert got["detail"] == [{"pullRequests": []}]
    await c.aclose()


async def test_remote_links_fixture():
    rl = _load("LUZ-158390.remotelinks.json")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/rest/api/3/issue/LUZ-158390/remotelink"
        return httpx.Response(200, json=rl)

    c = _client(handler)
    got = await c.get_issue_remote_links("LUZ-158390")
    assert any("49662787598" in o["object"]["url"] for o in got)
    await c.aclose()


async def test_search_jql_returns_keys_capped():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/rest/api/3/search/jql"
        assert request.url.params["jql"] == 'text ~ "export"'
        assert request.url.params["fields"] == "key"
        assert request.url.params["maxResults"] == "2"
        return httpx.Response(200, json={"issues": [{"key": "LUZ-1"}, {"key": "LUZ-2"}, {"x": 1}]})

    c = _client(handler)
    keys = await c.search_jql('text ~ "export"', max_results=2)
    assert keys == ["LUZ-1", "LUZ-2"]
    await c.aclose()


async def test_search_cql_returns_content_ids():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/wiki/rest/api/search"
        assert request.url.params["cql"] == 'text ~ "spec" AND type = page'
        assert request.url.params["limit"] == "10"
        return httpx.Response(200, json={"results": [
            {"content": {"id": "111", "type": "page"}},
            {"content": {"id": "222"}},
            {"user": {"accountId": "x"}},
        ]})

    c = _client(handler)
    ids = await c.search_cql('text ~ "spec" AND type = page')
    assert ids == ["111", "222"]
    await c.aclose()


async def test_retry_then_success(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(secs):
        sleeps.append(secs)

    monkeypatch.setattr("common.atlassian.base.asyncio.sleep", fake_sleep)

    n = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        n["calls"] += 1
        return httpx.Response(200, json={"ok": True}) if n["calls"] >= 3 else httpx.Response(503)

    c = _client(handler)
    got = await c._get("/x")
    assert got == {"ok": True}
    assert n["calls"] == 3
    assert sleeps == [1.0, 2.0]
    await c.aclose()


async def test_retry_exhausted_raises(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(secs):
        sleeps.append(secs)

    monkeypatch.setattr("common.atlassian.base.asyncio.sleep", fake_sleep)

    n = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        n["calls"] += 1
        return httpx.Response(503)

    c = _client(handler)
    with pytest.raises(httpx.HTTPStatusError):
        await c._get("/x")
    assert n["calls"] == 4
    assert sleeps == [1.0, 2.0, 4.0]
    await c.aclose()


async def test_404_is_not_retried(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(secs):
        sleeps.append(secs)

    monkeypatch.setattr("common.atlassian.base.asyncio.sleep", fake_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    c = _client(handler)
    with pytest.raises(httpx.HTTPStatusError):
        await c._get("/missing")
    assert sleeps == []
    await c.aclose()


def _bb_client(handler) -> AtlassianClient:
    transport = httpx.MockTransport(handler)
    return AtlassianClient(
        "https://example.atlassian.net",
        "user@example.com",
        "token",
        bitbucket_auth=("bbuser", "bbpass"),
        client=httpx.AsyncClient(transport=transport),
    )


async def test_get_bitbucket_repo():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.bitbucket.org"
        assert request.url.path == "/2.0/repositories/acme/luz-docs"
        return httpx.Response(200, json={"slug": "luz-docs"})

    c = _bb_client(handler)
    got = await c.get_bitbucket_repo("acme", "luz-docs")
    assert got["slug"] == "luz-docs"
    await c.aclose()


async def test_get_bitbucket_src_returns_raw_text():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/2.0/repositories/acme/luz-docs/src/main/FileUtil.java"
        assert request.headers.get("authorization", "").startswith("Basic ")
        return httpx.Response(200, text="class FileUtil {}")

    c = _bb_client(handler)
    src = await c.get_bitbucket_src("acme", "luz-docs", "FileUtil.java")
    assert "class FileUtil" in src
    await c.aclose()


# --- GitHub: Bearer-token auth + raw Contents API (public github.com + Enterprise Server) ---------

def _gh_client(handler, **kw) -> AtlassianClient:
    transport = httpx.MockTransport(handler)
    return AtlassianClient(
        "https://example.atlassian.net", "user@example.com", "token",
        github_token="ghp_x", client=httpx.AsyncClient(transport=transport), **kw,
    )


async def test_get_github_src_uses_bearer_and_raw_media_type():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.github.com"
        assert request.url.path == "/repos/acme/luz-docs/contents/FileUtil.java"
        assert request.url.params["ref"] == "main"
        assert request.headers.get("authorization") == "Bearer ghp_x"
        assert request.headers.get("accept") == "application/vnd.github.raw"
        return httpx.Response(200, text="class FileUtil {}")

    c = _gh_client(handler)
    src = await c.get_github_src("acme", "luz-docs", "FileUtil.java")
    assert "class FileUtil" in src
    await c.aclose()


async def test_get_github_src_enterprise_base_and_web_host():
    """GHE: API at <host>/api/v3, and github_web strips it back to the browser host."""
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "github.acme.com"
        assert request.url.path == "/api/v3/repos/acme/r/contents/F.java"
        return httpx.Response(200, text="ok")

    c = _gh_client(handler, github_base="https://github.acme.com/api/v3")
    assert await c.get_github_src("acme", "r", "F.java") == "ok"
    assert c.github_web == "https://github.acme.com"
    await c.aclose()


async def test_get_github_src_anonymous_when_no_token():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "authorization" not in request.headers
        return httpx.Response(200, text="public")

    transport = httpx.MockTransport(handler)
    c = AtlassianClient("https://example.atlassian.net", "user@example.com", "token",
                        client=httpx.AsyncClient(transport=transport))
    assert await c.get_github_src("acme", "r", "F.java") == "public"
    await c.aclose()


# --- download_bytes: SSRF guard (CLD-01) + streaming byte cap (CLD-02) ------------------------

async def test_download_bytes_blocks_ssrf_to_internal_literal():
    """CLD-01: a link-local/private attachment URL is refused BEFORE any connection."""
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not connect to a blocked host")

    c = _client(handler)
    with pytest.raises(ValueError, match="non-public"):
        await c.download_bytes("http://169.254.169.254/latest/meta-data/")
    await c.aclose()


async def test_download_bytes_blocks_ssrf_on_redirect_hop():
    """CLD-01: a public URL that 302-redirects to an internal host is caught on the hop."""
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "93.184.216.34"  # only the first (public) hop is ever attempted
        return httpx.Response(302, headers={"location": "http://10.0.0.1/internal"})

    c = _client(handler)
    with pytest.raises(ValueError, match="non-public"):
        await c.download_bytes("http://93.184.216.34/file")
    await c.aclose()


async def test_download_bytes_rejects_oversize_via_content_length():
    """CLD-02: the cap fires up-front on Content-Length, before the body is buffered."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"0123456789", headers={"content-type": "application/pdf"})

    c = _client(handler)
    with pytest.raises(ValueError, match="exceeds"):
        await c.download_bytes("http://93.184.216.34/big.pdf", max_bytes=4)
    await c.aclose()


async def test_download_bytes_streams_bytes_ctype_and_filename():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "93.184.216.34"
        return httpx.Response(200, content=b"hello world", headers={
            "content-type": "text/plain; charset=utf-8",
            "content-disposition": 'attachment; filename="notes.txt"'})

    c = _client(handler)
    data, ctype, filename = await c.download_bytes("http://93.184.216.34/notes.txt")
    assert data == b"hello world" and ctype == "text/plain" and filename == "notes.txt"
    await c.aclose()
