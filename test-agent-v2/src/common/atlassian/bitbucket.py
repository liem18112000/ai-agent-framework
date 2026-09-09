"""Bitbucket Cloud read-only endpoints (mixin over BaseClient; own host + auth)."""

from __future__ import annotations


class BitbucketMixin:
    async def get_bitbucket_repo(self, workspace: str, repo: str) -> dict:
        resp = await self._request(
            f"{self.bitbucket_base}/repositories/{workspace}/{repo}", auth=self._bb_auth
        )
        return resp.json()

    async def get_bitbucket_src(self, workspace: str, repo: str, path: str, ref: str = "main") -> str:
        """Raw file content at `path` on `ref` (returns text, not JSON)."""
        resp = await self._request(
            f"{self.bitbucket_base}/repositories/{workspace}/{repo}/src/{ref}/{path}",
            auth=self._bb_auth,
            accept=None,
        )
        return resp.text
