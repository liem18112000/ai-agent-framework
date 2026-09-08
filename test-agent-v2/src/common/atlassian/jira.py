"""Jira read-only endpoints (mixin over BaseClient)."""

from __future__ import annotations

_ISSUE_FIELDS = "summary,description,comment,issuelinks,attachment,parent,subtasks,labels,components"


class JiraMixin:
    async def get_issue(self, key: str) -> dict:
        return await self._get(f"/rest/api/3/issue/{key}", {"fields": _ISSUE_FIELDS})

    async def search_jql(self, jql: str, *, max_results: int = 10) -> list[str]:
        """Issue KEYS matching `jql` (first page only, capped at max_results)."""
        data = await self._get(
            "/rest/api/3/search/jql",
            {"jql": jql, "maxResults": max_results, "fields": "key"},
        )
        issues = data.get("issues", []) if isinstance(data, dict) else []
        return [k for i in issues if (k := i.get("key"))][:max_results]

    async def get_issue_remote_links(self, key: str) -> list[dict]:
        return await self._get(f"/rest/api/3/issue/{key}/remotelink")

    async def get_issue_dev_status(
        self, issue_id: str, data_type: str, application_type: str = "bitbucket"
    ) -> dict:
        """Development-panel detail (PRs / commits / branches) for an issue."""
        return await self._get(
            "/rest/dev-status/1.0/issue/detail",
            {"issueId": issue_id, "applicationType": application_type, "dataType": data_type},
        )
