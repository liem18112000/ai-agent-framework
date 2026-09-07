"""G1 Atlassian-search expansion — `atlassian_search_seeds` + the `_seed_probe` thinness gate.

Pure in-memory: fake clients expose only `search_jql`/`search_cql` (the expander) or `get_issue`
(the probe). No GCS, no network, no LLM.
"""

from __future__ import annotations

import pytest

from knowledge_gathering.executor.gather import SeedProbe, _seed_probe
from knowledge_gathering.explore.atlassian_search import _escape, atlassian_search_seeds


# --- fakes --- #
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


# --- _escape --- #
def test_escape_backslash_before_quote():
    assert _escape('a"b') == 'a\\"b'
    assert _escape('a\\b') == 'a\\\\b'
    assert _escape('a\\"b') == 'a\\\\\\"b'  # backslash escaped first, then the quote


# --- atlassian_search_seeds --- #
async def test_thin_seed_hits_promoted_with_prefixes():
    c = _FakeSearchClient(jira=["LUZ-2", "LUZ-3"], conf=["12345"])
    seeds, md = await atlassian_search_seeds(c, "export restricted folders", project="LUZ")
    assert seeds == ["confluence:12345", "jira:LUZ-2", "jira:LUZ-3"]  # dedup + stable sort
    assert md.startswith("Atlassian search (seed was thin) surfaced 3 related item(s):")
    assert "jira:LUZ-2" in md and "confluence:12345" in md


async def test_jql_scopes_project_and_escapes_query():
    c = _FakeSearchClient(jira=["LUZ-2"])
    await atlassian_search_seeds(c, 'alpha "beta" gamma', project="LUZ")
    assert 'project = "LUZ"' in c.last_jql
    assert c.last_jql.endswith("ORDER BY updated DESC")
    assert 'text ~ "alpha \\"beta\\" gamma"' in c.last_jql  # embedded quotes escaped
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
    assert seeds == ["confluence:10", "confluence:11", "jira:A-2"]  # sorted, then capped


async def test_jql_fails_cql_still_yields_hits():
    c = _FakeSearchClient(jira_exc=RuntimeError("no jira perm"), conf=["10", "11"])
    seeds, md = await atlassian_search_seeds(c, "export")
    assert seeds == ["confluence:10", "confluence:11"]  # per-call guard isolates the failure
    assert md


async def test_both_searches_failing_yields_empty():
    c = _FakeSearchClient(jira_exc=RuntimeError("x"), conf_exc=RuntimeError("y"))
    assert await atlassian_search_seeds(c, "export") == ([], "")


@pytest.mark.parametrize("terms", ["", "a of to"])  # empty / only short+stopword tokens
async def test_no_usable_tokens_skips_search(terms):
    c = _FakeSearchClient(jira=["A-1"])
    assert await atlassian_search_seeds(c, terms) == ([], "")
    assert c.last_jql is None  # never queried when there is nothing to search on


async def test_no_hits_yields_empty_md():
    c = _FakeSearchClient(jira=[], conf=[])
    assert await atlassian_search_seeds(c, "export") == ([], "")


# --- _seed_probe (the thinness gate that triggers G1) --- #
async def test_probe_thin_when_no_body_links_or_subtasks():
    c = _FakeIssueClient(_issue(summary="Export fails", labels=["earchive"], components=["Export"]))
    p = await _seed_probe(c, "LUZ-158390")
    assert p.thin is True
    assert "Export fails" in p.terms and "earchive" in p.terms and "Export" in p.terms
    assert p.project == "LUZ"
    # the raw fields the G2 hypothesize step reasons over are surfaced from the same fetch
    assert p.title == "Export fails" and p.labels == ["earchive"]


async def test_probe_not_thin_with_long_description():
    c = _FakeIssueClient(_issue(summary="X", desc="detail " * 60))  # > 200 chars
    p = await _seed_probe(c, "LUZ-1")
    assert p.thin is False
    assert p.description.startswith("detail")  # ADF body text surfaced for hypothesize


async def test_probe_not_thin_with_issuelinks():
    c = _FakeIssueClient(_issue(summary="X", links=["LUZ-2"]))
    assert (await _seed_probe(c, "LUZ-1")).thin is False


async def test_probe_not_thin_with_subtasks():
    c = _FakeIssueClient(_issue(summary="X", subtasks=["LUZ-2"]))
    assert (await _seed_probe(c, "LUZ-1")).thin is False


async def test_probe_non_jira_seed_returns_neutral():
    c = _FakeIssueClient(_issue(summary="X"))
    assert await _seed_probe(c, "12345") == SeedProbe()  # neutral, no fetch


async def test_probe_never_raises():
    class _Broken:
        async def get_issue(self, key):
            raise RuntimeError("boom")

    assert await _seed_probe(_Broken(), "LUZ-1") == SeedProbe()
