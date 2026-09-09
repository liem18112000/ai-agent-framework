"""External-web page fetcher (roadmap G3) — GET an already-linked public URL → a CITED leaf Note."""

from __future__ import annotations

import httpx

from common.extract.html_text import parse_html
from common.models import EXTERNAL_WEB, LinkRecord, Note, Scope
from knowledge_gathering.gather.crawl.fetch.base import NodeFetcher

_TIMEOUT = 10.0
_MAX_BYTES = 2 * 1024 * 1024
_MAX_REDIRECTS = 5
_ALLOWED_TYPES = ("text/html", "text/plain", "application/xhtml+xml")


def _build_client() -> httpx.AsyncClient:
    """Plain public-web client (NO Atlassian auth) — bounded timeout + redirects."""
    return httpx.AsyncClient(
        timeout=_TIMEOUT, follow_redirects=True, max_redirects=_MAX_REDIRECTS
    )


def _charset(content_type: str) -> str:
    ct = content_type.lower()
    if "charset=" in ct:
        return ct.split("charset=", 1)[1].split(";", 1)[0].strip() or "utf-8"
    return "utf-8"


async def _fetch_web(nid: str) -> tuple[list[LinkRecord], Note, str]:
    url = nid
    if url.split(":", 1)[0].lower() not in ("http", "https"):
        raise ValueError(f"unsupported scheme (http/https only): {url}")

    async with _build_client() as client, client.stream("GET", url) as resp:
        resp.raise_for_status()
        ctype = resp.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if ctype not in _ALLOWED_TYPES:
            raise ValueError(f"disallowed content-type {ctype!r}: {url}")
        chunks: list[bytes] = []
        total = 0
        async for chunk in resp.aiter_bytes():
            total += len(chunk)
            if total > _MAX_BYTES:
                raise ValueError(f"response exceeds {_MAX_BYTES} bytes: {url}")
            chunks.append(chunk)
        encoding = _charset(resp.headers.get("content-type", ""))

    html = b"".join(chunks).decode(encoding, errors="replace")
    text, title = parse_html(html)
    note = Note(id=nid, type=EXTERNAL_WEB, title=title or url, source_url=url, links=[])
    return [], note, text


class WebFetcher(NodeFetcher):
    """https:// external-web pages."""

    kind = "https"

    async def fetch(
        self, client, ident: str, nid: str, scope: Scope
    ) -> tuple[list[LinkRecord], Note, str]:
        return await _fetch_web(nid)


class WebFetcherHttp(WebFetcher):
    """http:// external-web pages — shares WebFetcher.fetch, registers under the ``http`` kind."""

    kind = "http"
