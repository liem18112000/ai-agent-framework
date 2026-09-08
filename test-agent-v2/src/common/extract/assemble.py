"""Assemble LinkRecords for a Jira issue / Confluence page from all sources."""

from __future__ import annotations

from common.extract.adf import adf_links, adf_text
from common.extract.classify import classify_url
from common.extract.regex_urls import regex_links
from common.extract.storage_html import storage_links
from common.models import CONFLUENCE_PAGE, JIRA_ISSUE, LinkRecord, Scope

_Raw = tuple[str, str, str, "str | None", "str | None"]


def _to_records(source_id: str, raw: list[_Raw], scope: Scope) -> list[LinkRecord]:
    seen: set[str] = set()
    out: list[LinkRecord] = []
    for url, anchor, origin, typ, canon in raw:
        if typ is None:
            typ, canon = classify_url(url)
        if canon in seen:
            continue
        seen.add(canon)
        out.append(
            LinkRecord(
                source_id=source_id,
                url=url,
                type=typ,
                origin=origin,
                anchor_text=anchor,
                canonical_url=canon,
                in_scope=scope.follows(typ),
            )
        )
    return out


def _dev_status_raw(details: list[dict]) -> list[_Raw]:
    """Flatten Jira dev-status ``detail[]`` entries into raw link candidates."""
    out: list[_Raw] = []
    for entry in details:
        for pr in entry.get("pullRequests", []) or []:
            if pr.get("url"):
                out.append((pr["url"], pr.get("name") or pr.get("id", ""), "pullrequest", None, None))
        for repo in entry.get("repositories", []) or []:
            if repo.get("url"):
                out.append((repo["url"], repo.get("name", ""), "repository", None, None))
            for commit in repo.get("commits", []) or []:
                if commit.get("url"):
                    anchor = commit.get("displayId") or commit.get("id", "")
                    out.append((commit["url"], anchor, "commit", None, None))
    return out


def extract_issue_links(
    issue: dict,
    remote_links: list[dict] | None = None,
    dev_status: list[dict] | None = None,
    *,
    base_url: str,
    scope: Scope,
) -> list[LinkRecord]:
    key = issue["key"]
    fields = issue.get("fields", {})
    raw: list[_Raw] = []

    desc = fields.get("description")
    raw += [(u, a, "description", None, None) for u, a in adf_links(desc)]
    raw += [(u, "", "regex", None, None) for u, _ in regex_links(adf_text(desc))]

    for comment in fields.get("comment", {}).get("comments", []):
        raw += [(u, a, "comment", None, None) for u, a in adf_links(comment.get("body"))]

    parent = fields.get("parent")
    if parent and parent.get("key"):
        pk = parent["key"]
        raw.append((f"{base_url}/browse/{pk}", pk, "parent", JIRA_ISSUE, f"jira:{pk}"))
    for sub in fields.get("subtasks", []) or []:
        if sub.get("key"):
            sk = sub["key"]
            raw.append((f"{base_url}/browse/{sk}", sk, "subtask", JIRA_ISSUE, f"jira:{sk}"))

    for link in fields.get("issuelinks", []):
        linked = link.get("inwardIssue") or link.get("outwardIssue")
        if linked and linked.get("key"):
            lk = linked["key"]
            raw.append((f"{base_url}/browse/{lk}", lk, "issuelink", JIRA_ISSUE, f"jira:{lk}"))

    for att in fields.get("attachment", []):
        if att.get("content"):
            raw.append((att["content"], att.get("filename", ""), "attachment", None, None))

    for rl in remote_links or []:
        obj = rl.get("object", {})
        if obj.get("url"):
            raw.append((obj["url"], obj.get("title", ""), "remotelink", None, None))

    raw += _dev_status_raw(dev_status or [])

    return _to_records(f"jira:{key}", raw, scope)


def extract_page_links(
    page: dict,
    children: dict | None = None,
    attachments: dict | None = None,
    *,
    base_url: str,
    scope: Scope,
) -> list[LinkRecord]:
    pid = str(page.get("id", ""))
    body = page.get("body", {}).get("storage", {}).get("value", "")
    raw: list[_Raw] = [(u, a, "body-storage", None, None) for u, a in storage_links(body)]

    for child in (children or {}).get("results", []):
        cid = child.get("id")
        if cid:
            raw.append(
                (
                    f"{base_url}/wiki/pages/viewpage.action?pageId={cid}",
                    child.get("title", ""),
                    "child",
                    CONFLUENCE_PAGE,
                    f"confluence:{cid}",
                )
            )

    for att in (attachments or {}).get("results", []):
        dl = att.get("downloadLink") or att.get("_links", {}).get("download")
        if dl:
            url = dl if dl.startswith("http") else f"{base_url}{dl}"
            raw.append((url, att.get("title", ""), "attachment", None, None))

    return _to_records(f"confluence:{pid}", raw, scope)
