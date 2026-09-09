"""G1 Atlassian-search expansion — `atlassian_search_seeds` + the `_seed_probe` thinness gate."""

from __future__ import annotations

import pytest

from knowledge_gathering.gather import SeedProbe, seed_probe
from knowledge_gathering.gather.explore.seeds.atlassian_search import (
    _escape,
    atlassian_search_seeds,
)


class _FakeSearchClient:
    def __init__(self, *, jira=None, conf=None, jira_exc=None, conf_exc=None):
        self._jira, self._conf = jira or [], conf or []
        self._jira_exc, self._conf_exc = jira_exc, conf_exc
        self.last_jql = self.last_cql = None

    async def search_jql(self, jql, *, max_results=10):
        self.last_jql = jql
        if self._jira_exc:
            raise self._jira_exc
        return self._jira

    async def search_cql(self, cql, *, limit=10):
        self.last_cql = cql
        if self._conf_exc:
            raise self._conf_exc
        return self._conf


def _adf(text: str) -> dict:
    body = [{"type": "paragraph", "content": [{"type": "text", "text": text}]}] if text else []
    return {"type": "doc", "version": 1, "content": body}


def _issue(*, summary="", desc="", links=(), subtasks=(), labels=(), components=()) -> dict:
    return {"fields": {
        "summary": summary,
        "description": _adf(desc),
        "issuelinks": [{"_": 1} for _ in links],
        "subtasks": [{"_": 1} for _ in subtasks],
        "labels": list(labels),
        "components": [{"name": c} for c in components],
    }}


class _FakeIssueClient:
    def __init__(self, issue: dict):
        self._issue = issue

    async def get_issue(self, key):
        return self._issue


def test_escape_backslash_before_quote():
    assert _escape('a"b') == 'a\\"b'
    assert _escape('a\\b') == 'a\\\\b'
    assert _escape('a\\"b') == 'a\\\\\\"b'


async def test_thin_seed_hits_promoted_with_prefixes():
    c = _FakeSearchClient(jira=["LUZ-2", "LUZ-3"], conf=["12345"])
    seeds, md = await atlassian_search_seeds(c, "export restricted folders", project="LUZ")
    assert seeds == ["confluence:12345", "jira:LUZ-2", "jira:LUZ-3"]
    assert md.startswith("Atlassian search (seed was thin) surfaced 3 related item(s):")
    assert "jira:LUZ-2" in md and "confluence:12345" in md


async def test_jql_scopes_project_and_escapes_query():
    c = _FakeSearchClient(jira=["LUZ-2"])
    await atlassian_search_seeds(c, 'alpha "beta" gamma', project="LUZ")
    assert 'project = "LUZ"' in c.last_jql
    assert c.last_jql.endswith("ORDER BY updated DESC")
    assert 'text ~ "alpha \\"beta\\" gamma"' in c.last_jql
    assert c.last_cql == 'text ~ "alpha \\"beta\\" gamma" AND type = page'


async def test_jql_omits_project_when_none():
    c = _FakeSearchClient(jira=["LUZ-2"])
    await atlassian_search_seeds(c, "export folders")
    assert "project" not in c.last_jql.lower()
    assert c.last_jql.startswith("text ~ ")


async def test_excludes_seed_and_excluded_ids():
    c = _FakeSearchClient(jira=["SEED-1", "A-2", "A-3"], conf=["10"])
    seeds, _ = await atlassian_search_seeds(
        c, "export", exclude={"jira:SEED-1", "jira:A-3"})
    assert set(seeds) == {"jira:A-2", "confluence:10"}


async def test_caps_at_max_seeds_stable_order():
    c = _FakeSearchClient(jira=[f"A-{i}" for i in range(2, 8)], conf=["10", "11"])
    seeds, _ = await atlassian_search_seeds(c, "export", max_seeds=3)
    assert seeds == ["confluence:10", "confluence:11", "jira:A-2"]


async def test_jql_fails_cql_still_yields_hits():
    c = _FakeSearchClient(jira_exc=RuntimeError("no jira perm"), conf=["10", "11"])
    seeds, md = await atlassian_search_seeds(c, "export")
    assert seeds == ["confluence:10", "confluence:11"]
    assert md


async def test_both_searches_failing_yields_empty():
    c = _FakeSearchClient(jira_exc=RuntimeError("x"), conf_exc=RuntimeError("y"))
    assert await atlassian_search_seeds(c, "export") == ([], "")


@pytest.mark.parametrize("terms", ["", "a of to"])
async def test_no_usable_tokens_skips_search(terms):
    c = _FakeSearchClient(jira=["A-1"])
    assert await atlassian_search_seeds(c, terms) == ([], "")
    assert c.last_jql is None


async def test_no_hits_yields_empty_md():
    c = _FakeSearchClient(jira=[], conf=[])
    assert await atlassian_search_seeds(c, "export") == ([], "")


async def test_probe_thin_when_no_body_links_or_subtasks():
    c = _FakeIssueClient(_issue(summary="Export fails", labels=["earchive"], components=["Export"]))
    p = await seed_probe(c, "LUZ-158390")
    assert p.thin is True
    assert "Export fails" in p.terms and "earchive" in p.terms and "Export" in p.terms
    assert p.project == "LUZ"
    assert p.title == "Export fails" and p.labels == ["earchive"]


async def test_probe_not_thin_with_long_description():
    c = _FakeIssueClient(_issue(summary="X", desc="detail " * 60))
    p = await seed_probe(c, "LUZ-1")
    assert p.thin is False
    assert p.description.startswith("detail")


async def test_probe_not_thin_with_issuelinks():
    c = _FakeIssueClient(_issue(summary="X", links=["LUZ-2"]))
    assert (await seed_probe(c, "LUZ-1")).thin is False


async def test_probe_not_thin_with_subtasks():
    c = _FakeIssueClient(_issue(summary="X", subtasks=["LUZ-2"]))
    assert (await seed_probe(c, "LUZ-1")).thin is False


async def test_probe_non_jira_seed_returns_neutral():
    c = _FakeIssueClient(_issue(summary="X"))
    assert await seed_probe(c, "12345") == SeedProbe()


async def test_probe_never_raises():
    class _Broken:
        async def get_issue(self, key):
            raise RuntimeError("boom")

    assert await seed_probe(_Broken(), "LUZ-1") == SeedProbe()
