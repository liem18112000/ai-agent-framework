"""External-web page fetcher (roadmap G3) — GET an already-linked public URL → a CITED leaf Note."""

from __future__ import annotations

import ipaddress
import socket

import httpx

from common.extract.html_text import parse_html
from common.models import EXTERNAL_WEB, LinkRecord, Note, Scope
from knowledge_gathering.gather.crawl.fetch.base import NodeFetcher

_TIMEOUT = 10.0
_MAX_BYTES = 2 * 1024 * 1024
_MAX_REDIRECTS = 5
_ALLOWED_TYPES = ("text/html", "text/plain", "application/xhtml+xml")
_BLOCKED_HOSTS = frozenset({"localhost", "metadata", "metadata.google.internal"})


class BlockedHostError(ValueError):
    """SSRF guard tripped — the fetch (or a redirect hop) targeted a non-public host."""


def _ip_blocked(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return (addr.is_private or addr.is_loopback or addr.is_link_local
            or addr.is_reserved or addr.is_multicast or addr.is_unspecified)


def _host_blocked(host: str | None) -> bool:
    """True if `host` is non-public: a private/loopback/link-local/reserved IP literal, a known
    internal name, or a hostname that *resolves* to such an address. Fail-open on a resolution error —
    a name that can't resolve can't be connected to anyway."""
    host = (host or "").strip().lower().rstrip(".")
    if not host or host in _BLOCKED_HOSTS:
        return True
    try:
        ipaddress.ip_address(host)  # bare IP literal (v4/v6, brackets already stripped by URL.host)
        return _ip_blocked(host)
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    return any(_ip_blocked(info[4][0]) for info in infos)


async def _guard_request(request: httpx.Request) -> None:
    """httpx request event-hook — reject SSRF to non-public hosts on the initial URL AND every redirect
    hop (the hook runs once per request in the redirect chain)."""
    if _host_blocked(request.url.host):
        raise BlockedHostError(f"blocked non-public address: {request.url}")


def _build_client() -> httpx.AsyncClient:
    """Plain public-web client (NO Atlassian auth) — bounded timeout/redirects + SSRF guard per hop."""
    return httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True, max_redirects=_MAX_REDIRECTS,
                             event_hooks={"request": [_guard_request]})


async def _fetch_web(nid: str) -> tuple[list[LinkRecord], Note, str]:
    if nid.split(":", 1)[0].lower() not in ("http", "https"):
        raise ValueError(f"unsupported scheme (http/https only): {nid}")

    async with _build_client() as client, client.stream("GET", nid) as resp:
        resp.raise_for_status()
        ctype = resp.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if ctype not in _ALLOWED_TYPES:
            raise ValueError(f"disallowed content-type {ctype!r}: {nid}")
        chunks: list[bytes] = []
        total = 0
        async for chunk in resp.aiter_bytes():
            total += len(chunk)
            if total > _MAX_BYTES:
                raise ValueError(f"response exceeds {_MAX_BYTES} bytes: {nid}")
            chunks.append(chunk)
        encoding = resp.charset_encoding or "utf-8"

    text, title = parse_html(b"".join(chunks).decode(encoding, errors="replace"))
    return [], Note(id=nid, type=EXTERNAL_WEB, title=title or nid, source_url=nid, links=[]), text


class WebFetcher(NodeFetcher):
    """https:// external-web pages."""

    kind = "https"

    async def fetch(self, client, ident: str, nid: str, scope: Scope) -> tuple[list[LinkRecord], Note, str]:
        return await _fetch_web(nid)


class WebFetcherHttp(WebFetcher):
    """http:// external-web pages — shares WebFetcher.fetch, registers under the ``http`` kind."""

    kind = "http"
