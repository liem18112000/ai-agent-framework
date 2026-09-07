"""External-web page fetcher (roadmap G3) — GET an already-linked public URL → a CITED leaf Note.

Makes only URLs that tickets ALREADY link fetchable (no active web *search*). Gated upstream by
``Scope.follow_web`` (default OFF) + a crawl web sub-budget, so default gather is unchanged.
Registered for BOTH ``http`` and ``https`` kinds via two thin classes over one impl (Open/Closed).

Safety (always on): http/https only · ~10s timeout · ~2 MB cap · text content-type allowlist ·
bounded redirects. ANY failure RAISES → the crawl records a declared gap (never a fake note).

FOLLOW-UP (not built): SSRF / private-IP hardening — before enabling broadly, reject URLs
resolving to private/loopback/link-local/metadata ranges (169.254.169.254, 10/8, 127/8, ::1, …)
and re-check every redirect hop, so a malicious link can't pivot into internal services.
"""

from __future__ import annotations

import httpx

from common.extract.html_text import parse_html
from common.models import EXTERNAL_WEB, LinkRecord, Note, Scope
from knowledge_gathering.loop.fetch.base import NodeFetcher

_TIMEOUT = 10.0  # connect + read seconds
_MAX_BYTES = 2 * 1024 * 1024  # 2 MB response cap
_MAX_REDIRECTS = 5
_ALLOWED_TYPES = ("text/html", "text/plain", "application/xhtml+xml")


def _build_client() -> httpx.AsyncClient:
    """Plain public-web client (NO Atlassian auth) — bounded timeout + redirects.

    A module-level factory so tests can inject an httpx.MockTransport (no real network).
    """
    return httpx.AsyncClient(
        timeout=_TIMEOUT, follow_redirects=True, max_redirects=_MAX_REDIRECTS
    )


def _charset(content_type: str) -> str:
    ct = content_type.lower()
    if "charset=" in ct:
        return ct.split("charset=", 1)[1].split(";", 1)[0].strip() or "utf-8"
    return "utf-8"


async def _fetch_web(nid: str) -> tuple[list[LinkRecord], Note, str]:
    # For external-web, the canonical node id IS the full URL (classify_url returns the raw URL).
    url = nid
    if url.split(":", 1)[0].lower() not in ("http", "https"):
        raise ValueError(f"unsupported scheme (http/https only): {url}")

    async with _build_client() as client, client.stream("GET", url) as resp:
        resp.raise_for_status()  # non-200 → raise → crawl gaps it
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
    # Cited via source_url; leave synopsis unset so crawl's distiller fills it (cf. confluence.py).
    note = Note(id=nid, type=EXTERNAL_WEB, title=title or url, source_url=url, links=[])
    return [], note, text  # leaf: no outbound links → never expands the frontier


class WebFetcher(NodeFetcher):
    """https:// external-web pages."""

    kind = "https"

    async def fetch(
        self, client, ident: str, nid: str, scope: Scope
    ) -> tuple[list[LinkRecord], Note, str]:
        # `client` (the Atlassian client) is ignored — these are public URLs, no auth.
        return await _fetch_web(nid)


class WebFetcherHttp(WebFetcher):
    """http:// external-web pages — shares WebFetcher.fetch, registers under the ``http`` kind."""

    kind = "http"
