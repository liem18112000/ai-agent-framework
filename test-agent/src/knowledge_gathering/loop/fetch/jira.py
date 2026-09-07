"""Jira issue fetcher."""

from __future__ import annotations

from common.extract import extract_issue_links
from common.extract.adf import adf_text
from common.models import JIRA_ISSUE, LinkRecord, Note, Scope
from knowledge_gathering.loop.fetch.base import NodeFetcher
from knowledge_gathering.monitoring import get_logger

log = get_logger("loop.fetch.jira")


async def _dev_status(client, issue: dict) -> list[dict]:
    """Best-effort dev-panel detail (PRs + commits + repos), or [] when there's no dev-status
    endpoint (a repo-less issue is normal, not a gap). Keyed on the numeric issue['id'], not the key."""
    fetch = getattr(client, "get_issue_dev_status", None)
    issue_id = issue.get("id")
    if not fetch or not issue_id:
        return []
    details: list[dict] = []
    for data_type in ("pullrequest", "repository"):
        try:
            resp = await fetch(issue_id, data_type)
        except Exception as exc:  # noqa: BLE001 — no integration / 400 → simply no dev info
            log.debug("dev-status %s unavailable for %s: %s", data_type, issue_id, exc)
            continue
        details.extend(resp.get("detail", []) or [])
    return details


class JiraFetcher(NodeFetcher):
    kind = "jira"

    async def fetch(
        self, client, ident: str, nid: str, scope: Scope
    ) -> tuple[list[LinkRecord], Note, str]:
        issue = await client.get_issue(ident)
        remote = await client.get_issue_remote_links(ident)
        dev = await _dev_status(client, issue)
        links = extract_issue_links(issue, remote, dev, base_url=client.base_url, scope=scope)
        f = issue.get("fields", {})
        body = adf_text(f.get("description"))
        # Pre-fill the synopsis with the real AC body (capped) so the interrogation sees actual
        # acceptance criteria, not the one-line distill. crawl.py honors a pre-set synopsis.
        note = Note(
            id=nid, type=JIRA_ISSUE, title=f.get("summary", ""),
            source_url=f"{client.base_url}/browse/{ident}", links=links, synopsis=body[:1500],
        )
        return links, note, body
