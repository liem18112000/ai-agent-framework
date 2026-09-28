"""GitHub read-only endpoints (mixin over BaseClient) — public github.com + Enterprise Server.

Auth is a Personal Access Token via `Authorization: Bearer <token>` (fine-grained: Contents=read;
classic: `repo`/`public_repo`). No token → anonymous (public repos only, 60 req/h rate limit).
The API host is the client's `github_base` (`https://api.github.com`, or `https://<host>/api/v3` for GHE).
"""

from __future__ import annotations

_API_VERSION = "2022-11-28"


class GitHubMixin:
    def _gh_headers(self) -> dict[str, str]:
        h = {"X-GitHub-Api-Version": _API_VERSION}
        if self._gh_token:
            h["Authorization"] = f"Bearer {self._gh_token}"
        return h

    async def get_github_repo(self, owner: str, repo: str) -> dict:
        resp = await self._request(f"{self.github_base}/repos/{owner}/{repo}", headers=self._gh_headers())
        return resp.json()

    async def get_github_src(self, owner: str, repo: str, path: str, ref: str = "main") -> str:
        """Raw file content at `path` on `ref` (returns text, not JSON).

        The Contents API with `Accept: application/vnd.github.raw` streams the file directly. Fetched
        via `stream_text`: streamed with a byte cap (owner/repo/path/ref derive from untrusted ticket
        content), SSRF-guarded, and 3xx-rejected — a blob over the cap is refused without being
        buffered into RAM, so the crawl records a gap instead of OOMing. Larger blobs would need the
        Git Blobs API — add when a repo actually hits the cap.
        """
        return await self.stream_text(
            f"{self.github_base}/repos/{owner}/{repo}/contents/{path}",
            params={"ref": ref},
            accept="application/vnd.github.raw",
            headers=self._gh_headers(),
        )
