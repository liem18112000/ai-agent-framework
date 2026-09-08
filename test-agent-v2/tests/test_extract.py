"""M1 tests: link extraction against the LUZ-158390 known-good fixtures."""

from __future__ import annotations

import json
from pathlib import Path

from common.extract import classify_url, extract_issue_links, extract_page_links
from common.models import (
    ATTACHMENT,
    BITBUCKET,
    CODEGRAPH,
    CONFLUENCE_PAGE,
    EXTERNAL_WEB,
    FIGMA,
    JIRA_ISSUE,
    Scope,
)

FIX = Path(__file__).parent / "fixtures"
BASE = "https://axonivy.atlassian.net"
SCOPE = Scope()


def _load(name: str):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def _issue_records():
    return extract_issue_links(
        _load("LUZ-158390.issue.json"),
        _load("LUZ-158390.remotelinks.json"),
        base_url=BASE,
        scope=SCOPE,
    )


def test_classify_url():
    assert classify_url(f"{BASE}/browse/LUZ-159670") == (JIRA_ISSUE, "jira:LUZ-159670")
    assert classify_url(f"{BASE}/wiki/spaces/LUZ/pages/49662787598/Perf") == (
        CONFLUENCE_PAGE,
        "confluence:49662787598",
    )
    assert classify_url("https://bitbucket.org/acme/x") == (CODEGRAPH, "codegraph:acme/x")
    assert classify_url("https://bitbucket.org/acme/x/pull-requests/9")[0] == BITBUCKET
    assert classify_url("https://www.figma.com/file/abc")[0] == FIGMA
    assert classify_url("https://example.com/spec.pdf")[0] == EXTERNAL_WEB


def test_every_link_found_none_dropped():
    canon = {r.canonical_url for r in _issue_records()}
    assert canon == {
        "confluence:49662787598",
        "https://example.com/spec.pdf",
        "bitbucket:acme/luz-docs/src/main/FileUtil.java",
        "https://www.figma.com/file/abc/eArchive",
        "jira:LUZ-159670",
        "jira:LUZ-159671",
        "https://axonivy.atlassian.net/rest/api/3/attachment/content/10001",
        "https://confluence.example.com/display/LUZ/eArchive-Spec",
    }


def test_follow_vs_record_only():
    by_canon = {r.canonical_url: r for r in _issue_records()}
    assert by_canon["confluence:49662787598"].in_scope is True
    assert by_canon["jira:LUZ-159670"].in_scope is True
    assert by_canon["jira:LUZ-159671"].in_scope is True
    for canon in (
        "bitbucket:acme/luz-docs/src/main/FileUtil.java",
        "https://www.figma.com/file/abc/eArchive",
        "https://example.com/spec.pdf",
        "https://axonivy.atlassian.net/rest/api/3/attachment/content/10001",
    ):
        assert by_canon[canon].in_scope is False


def test_origins_recorded():
    by_canon = {r.canonical_url: r for r in _issue_records()}
    assert by_canon["confluence:49662787598"].origin == "description"
    assert by_canon["https://example.com/spec.pdf"].origin == "regex"
    assert by_canon["https://www.figma.com/file/abc/eArchive"].origin == "comment"
    assert by_canon["jira:LUZ-159670"].origin == "issuelink"


def test_confluence_smart_link_type():
    bit = next(
        r for r in _issue_records() if r.canonical_url.startswith("bitbucket:")
    )
    assert bit.type == BITBUCKET and bit.origin == "description"
    att = next(r for r in _issue_records() if r.type == ATTACHMENT)
    assert att.anchor_text == "transfer.zip"


def test_parent_subtask_and_dev_panel_links():
    """Parent/subtasks (followable) + dev-panel PRs/commits/repo (recorded) — the LUZ-159312 gap."""
    issue = {
        "key": "LUZ-159312",
        "id": "10042",
        "fields": {
            "summary": "Functional Test & Performance test",
            "parent": {"key": "LUZ-159000"},
            "subtasks": [{"key": "LUZ-159313"}, {"key": "LUZ-159314"}],
        },
    }
    dev = [
        {
            "pullRequests": [
                {"id": "#42", "name": "perf test",
                 "url": "https://bitbucket.org/axonivy-prod/luz_docs/pull-requests/42"}
            ],
            "repositories": [
                {"name": "luz_docs", "url": "https://bitbucket.org/axonivy-prod/luz_docs",
                 "commits": [
                     {"displayId": "abc1234", "id": "abc1234ff",
                      "url": "https://bitbucket.org/axonivy-prod/luz_docs/commits/abc1234ff"}
                 ]},
            ],
        }
    ]
    recs = {
        r.canonical_url: r
        for r in extract_issue_links(issue, None, dev, base_url=BASE, scope=SCOPE)
    }
    assert recs["jira:LUZ-159000"].origin == "parent" and recs["jira:LUZ-159000"].in_scope
    assert recs["jira:LUZ-159313"].origin == "subtask" and recs["jira:LUZ-159313"].in_scope
    assert recs["jira:LUZ-159314"].in_scope
    repo = recs["codegraph:axonivy-prod/luz_docs"]
    assert repo.type == CODEGRAPH and repo.origin == "repository" and repo.in_scope is False
    pr = recs["https://bitbucket.org/axonivy-prod/luz_docs/pull-requests/42"]
    assert pr.type == BITBUCKET and pr.origin == "pullrequest" and pr.in_scope is False
    commit = recs["https://bitbucket.org/axonivy-prod/luz_docs/commits/abc1234ff"]
    assert commit.type == BITBUCKET and commit.origin == "commit"


def test_extract_page_links():
    recs = extract_page_links(
        _load("confluence-49662787598.page.json"),
        children={"results": [{"id": "111", "title": "Child A"}]},
        base_url=BASE,
        scope=SCOPE,
    )
    by_canon = {r.canonical_url: r for r in recs}
    assert by_canon["jira:LUZ-158390"].in_scope is True
    assert by_canon["jira:LUZ-158390"].origin == "body-storage"
    assert by_canon["https://grafana.example.com/d/abc/earchive"].in_scope is False
    assert by_canon["confluence:111"].in_scope is True
    assert by_canon["confluence:111"].origin == "child"
