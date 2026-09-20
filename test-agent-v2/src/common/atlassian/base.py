"""Shared config + retry core for the read-only Atlassian clients (GET-only)."""

from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx

from common.monitoring import get_logger
from common.net import BlockedHostError, host_blocked

log = get_logger("atlassian")

_DISPOSITION_FILENAME = re.compile(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", re.IGNORECASE)
_MAX_REDIRECTS = 5
_REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})


def _filename_from_disposition(disposition: str) -> str:
    """Pull the filename out of a Content-Disposition header (RFC 6266 `filename` / `filename*`)."""
    m = _DISPOSITION_FILENAME.search(disposition or "")
    return m.group(1).strip() if m else ""

RETRY_BACKOFFS: tuple[float, ...] = (1.0, 2.0, 4.0)
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
BITBUCKET_API = "https://api.bitbucket.org/2.0"


def _retryable(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRY_STATUS
    return isinstance(exc, httpx.TransportError)


class BaseClient:
    """Config + retry core; service mixins add the endpoint methods."""

    def __init__(
        self, base_url: str, email: str, api_token: str, *,
        bitbucket_auth: tuple[str, str] | None = None, bitbucket_base: str = BITBUCKET_API,
        client: httpx.AsyncClient | None = None, backoffs: tuple[float, ...] = RETRY_BACKOFFS,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._auth = (email, api_token)
        self.bitbucket_base = bitbucket_base.rstrip("/")
        self._bb_auth = bitbucket_auth
        self._backoffs = backoffs
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def _request(
        self, url: str, params: dict | None = None, auth: tuple[str, str] | None = None,
        *, accept: str | None = "application/json", follow_redirects: bool = False,
    ) -> httpx.Response:
        """GET `url` with bounded retry on transient failures."""
        headers = {"Accept": accept} if accept else {}
        for attempt in range(len(self._backoffs) + 1):
            try:
                resp = await self._client.get(url, params=params, auth=auth, headers=headers,
                                              follow_redirects=follow_redirects)
                resp.raise_for_status()
                return resp
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                if not _retryable(exc) or attempt == len(self._backoffs):
                    raise
                wait = self._backoffs[attempt]
                log.warning("retry %d/%d in %.0fs: %s (%s)", attempt + 1, len(self._backoffs), wait, url, exc)
                await asyncio.sleep(wait)
        raise AssertionError("unreachable")

    async def _get(self, path: str, params: dict | None = None) -> Any:
        """Site (Jira/Confluence) JSON GET, relative to base_url."""
        resp = await self._request(f"{self.base_url}{path}", params, self._auth)
        return resp.json()

    async def download_bytes(self, url: str, *, max_bytes: int = 25 * 1024 * 1024) -> tuple[bytes, str, str]:
        """Authenticated GET of an attachment `url` → (bytes, content_type, filename).

        SSRF-guarded (root cause #1): the initial URL and every redirect hop are rejected via
        `common.net.host_blocked` before any connection — the `url` comes from a Jira/Confluence
        attachment record inside the ticket under test, so it is untrusted. Redirects are followed
        manually (follow_redirects off) so each hop is checked; Basic-auth is re-sent only while still
        on the original host (dropped cross-origin, which is right for a pre-signed media URL).

        Streams the body with an up-front Content-Length check and a cumulative byte cap, so a body
        over `max_bytes` is refused without being buffered into RAM (→ the crawl records a gap instead
        of OOMing on a huge/attacker-sized blob)."""
        current = url
        origin = httpx.URL(url).host
        for _ in range(_MAX_REDIRECTS + 1):
            if host_blocked(httpx.URL(current).host):
                raise BlockedHostError(f"blocked non-public address: {current}")
            auth = self._auth if httpx.URL(current).host == origin else None
            async with self._client.stream(
                "GET", current, auth=auth, headers={"Accept": "*/*"}, follow_redirects=False,
            ) as resp:
                if resp.status_code in _REDIRECT_CODES and resp.headers.get("location"):
                    current = str(resp.url.join(resp.headers["location"]))
                    continue
                resp.raise_for_status()
                declared = resp.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > max_bytes:
                    raise ValueError(f"attachment exceeds {max_bytes} bytes: {url}")
                chunks: list[bytes] = []
                total = 0
                async for chunk in resp.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError(f"attachment exceeds {max_bytes} bytes: {url}")
                    chunks.append(chunk)
                ctype = resp.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                filename = _filename_from_disposition(resp.headers.get("content-disposition", ""))
                return b"".join(chunks), ctype, filename
        raise ValueError(f"too many redirects (> {_MAX_REDIRECTS}): {url}")

    async def aclose(self) -> None:
        await self._client.aclose()
