"""Shared config + retry core for the read-only Atlassian clients (GET-only)."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from common.monitoring import get_logger

log = get_logger("atlassian")

RETRY_BACKOFFS: tuple[float, ...] = (1.0, 2.0, 4.0)  # wait before each retry
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
BITBUCKET_API = "https://api.bitbucket.org/2.0"


def _retryable(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRY_STATUS
    return isinstance(exc, httpx.TransportError)


class BaseClient:
    """Config + retry core; service mixins add the endpoint methods."""

    def __init__(
        self,
        base_url: str,
        email: str,
        api_token: str,
        *,
        bitbucket_auth: tuple[str, str] | None = None,
        bitbucket_base: str = BITBUCKET_API,
        client: httpx.AsyncClient | None = None,
        backoffs: tuple[float, ...] = RETRY_BACKOFFS,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._auth = (email, api_token)
        self.bitbucket_base = bitbucket_base.rstrip("/")
        self._bb_auth = bitbucket_auth
        self._backoffs = backoffs
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def _request(
        self,
        url: str,
        params: dict | None = None,
        auth: tuple[str, str] | None = None,
        *,
        accept: str | None = "application/json",
    ) -> httpx.Response:
        """GET `url` with bounded retry on transient failures."""
        headers = {"Accept": accept} if accept else {}
        for attempt in range(len(self._backoffs) + 1):
            try:
                resp = await self._client.get(url, params=params, auth=auth, headers=headers)
                resp.raise_for_status()
                return resp
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                if not _retryable(exc) or attempt == len(self._backoffs):
                    raise
                wait = self._backoffs[attempt]
                log.warning("retry %d/%d in %.0fs: %s (%s)",
                            attempt + 1, len(self._backoffs), wait, url, exc)
                await asyncio.sleep(wait)
        raise AssertionError("unreachable")

    async def _get(self, path: str, params: dict | None = None) -> Any:
        """Site (Jira/Confluence) JSON GET, relative to base_url."""
        resp = await self._request(f"{self.base_url}{path}", params, self._auth)
        return resp.json()

    async def aclose(self) -> None:
        await self._client.aclose()
