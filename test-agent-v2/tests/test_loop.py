"""M3 tests: the bounded frontier crawl (dedup, budget, gaps, record-only)."""

from __future__ import annotations

import asyncio

import pytest

from common.memory import MemoryBank
from common.store import CASConflict
from knowledge_gathering.gather.crawl import crawl
from knowledge_gathering.gather.seed import normalize_seed

BASE = "https://axonivy.atlassian.net"


class FakeBlob:
    def __init__(self, bucket, name):
        self._b, self.name = bucket, name

    @property
    def generation(self):
        return self._b.gens.get(self.name, 0)

    def download_as_text(self):
        return self._b.store[self.name]

    def upload_from_string(self, data, content_type=None, if_generation_match=None):
        cur = self._b.gens.get(self.name, 0)
        if if_generation_match is not None and if_generation_match != cur:
            raise CASConflict("gen mismatch")
        self._b.store[self.name] = data
        self._b.gens[self.name] = cur + 1


class FakeBucket:
    def __init__(self):
        self.store, self.gens = {}, {}

    def blob(self, name):
        return FakeBlob(self, name)

    def get_blob(self, name):
        return FakeBlob(self, name) if name in self.store else None


def _issue(key, links_to=(), bitbucket=False, github=False):
    content = []
    for lk in links_to:
        pass
    if bitbucket:
        content.append({"type": "paragraph", "content": [
            {"type": "inlineCard", "attrs": {"url": "https://bitbucket.org/acme/r/src/main/F.java"}}]})
    if github:
        content.append({"type": "paragraph", "content": [
            {"type": "inlineCard", "attrs": {"url": "https://github.com/acme/r/blob/main/F.java"}}]})
    return {
        "key": key,
        "fields": {
            "summary": f"Issue {key}",
            "description": {"type": "doc", "version": 1, "content": content},
            "issuelinks": [{"type": {"name": "Relates"}, "outwardIssue": {"key": lk}} for lk in links_to],
        },
    }


class FakeClient:
    base_url = BASE

    def __init__(self, issues, fail=(), files=None):
        self.issues, self.fail = issues, set(fail)
        self.files = files or {}
        self.gets: list[str] = []

    async def get_issue(self, key):
        self.gets.append(key)
        if key in self.fail:
            raise RuntimeError(f"boom {key}")
        return self.issues[key]

    async def get_issue_remote_links(self, key):
        return []

    async def get_bitbucket_src(self, ws, repo, path, ref="main"):
        return self.files[(ws, repo, ref, path)]

    github_web = "https://github.com"

    async def get_github_src(self, owner, repo, path, ref="main"):
        return self.files[(owner, repo, ref, path)]


def test_normalize_seed():
    assert normalize_seed("LUZ-158390") == "jira:LUZ-158390"
    assert normalize_seed("49662787598") == "confluence:49662787598"
    assert normalize_seed(f"{BASE}/browse/LUZ-1") == "jira:LUZ-1"


async def test_two_hop_crawl_with_dedup_and_record_only():
    issues = {
        "LUZ-1": _issue("LUZ-1", links_to=["LUZ-2"], bitbucket=True),
        "LUZ-2": _issue("LUZ-2", links_to=["LUZ-1"]),
    }
    client = FakeClient(issues)
    result = await crawl(client, MemoryBank(FakeBucket()), "LUZ-1", depth=2, run_id="t")

    got = {n.id for n in result.notes}
    assert got == {"jira:LUZ-1", "jira:LUZ-2"}
    assert client.gets.count("LUZ-1") == 1
    canons = {lr.canonical_url for lr in result.inventory}
    assert "bitbucket:acme/r/src/main/F.java" in canons
    assert not any(n.id.startswith("bitbucket") for n in result.notes)


async def test_depth_zero_only_seed():
    issues = {"LUZ-1": _issue("LUZ-1", links_to=["LUZ-2"]), "LUZ-2": _issue("LUZ-2")}
    result = await crawl(FakeClient(issues), MemoryBank(FakeBucket()), "LUZ-1", depth=0, run_id="t")
    assert {n.id for n in result.notes} == {"jira:LUZ-1"}


async def test_max_nodes_budget():
    issues = {f"LUZ-{i}": _issue(f"LUZ-{i}", links_to=[f"LUZ-{i + 1}"]) for i in range(10)}
    issues["LUZ-10"] = _issue("LUZ-10")
    result = await crawl(FakeClient(issues), MemoryBank(FakeBucket()), "LUZ-0",
                         depth=99, max_nodes=3, run_id="t")
    assert len(result.notes) == 3


async def test_fetch_failure_becomes_gap():
    issues = {"LUZ-1": _issue("LUZ-1", links_to=["LUZ-2"]), "LUZ-2": _issue("LUZ-2")}
    client = FakeClient(issues, fail=["LUZ-2"])
    result = await crawl(client, MemoryBank(FakeBucket()), "LUZ-1", depth=2, run_id="t")
    assert {n.id for n in result.notes} == {"jira:LUZ-1"}
    assert result.gaps == ["jira:LUZ-2"]


async def test_follows_bitbucket_file_only_when_in_scope():
    from common.models import BITBUCKET, CONFLUENCE_PAGE, JIRA_ISSUE, Scope

    issues = {"LUZ-1": _issue("LUZ-1", bitbucket=True)}
    src = {("acme", "r", "main", "F.java"): "class F { void extractAllZipFile() {} }"}

    scope = Scope(follow_types=(JIRA_ISSUE, CONFLUENCE_PAGE, BITBUCKET))
    result = await crawl(FakeClient(issues, files=src), MemoryBank(FakeBucket()),
                         "LUZ-1", depth=1, scope=scope, run_id="t")
    assert "bitbucket:acme/r/src/main/F.java" in {n.id for n in result.notes}
    bb = next(n for n in result.notes if n.type == BITBUCKET)
    assert "extractAllZipFile" in bb.synopsis

    default = await crawl(FakeClient(issues, files=src), MemoryBank(FakeBucket()),
                          "LUZ-1", depth=1, run_id="t")
    assert not any(n.type == BITBUCKET for n in default.notes)


async def test_follows_github_file_only_when_in_scope():
    from common.models import CONFLUENCE_PAGE, GITHUB, JIRA_ISSUE, Scope

    issues = {"LUZ-1": _issue("LUZ-1", github=True)}
    src = {("acme", "r", "main", "F.java"): "class F { void extractAllZipFile() {} }"}

    scope = Scope(follow_types=(JIRA_ISSUE, CONFLUENCE_PAGE, GITHUB))
    result = await crawl(FakeClient(issues, files=src), MemoryBank(FakeBucket()),
                         "LUZ-1", depth=1, scope=scope, run_id="t")
    assert "github:acme/r/blob/main/F.java" in {n.id for n in result.notes}
    gh = next(n for n in result.notes if n.type == GITHUB)
    assert "extractAllZipFile" in gh.synopsis

    default = await crawl(FakeClient(issues, files=src), MemoryBank(FakeBucket()),
                          "LUZ-1", depth=1, run_id="t")
    assert not any(n.type == GITHUB for n in default.notes)


async def test_extra_seeds_are_crawled_at_depth_zero():
    issues = {"LUZ-1": _issue("LUZ-1"), "LUZ-3": _issue("LUZ-3")}
    result = await crawl(FakeClient(issues), MemoryBank(FakeBucket()), "LUZ-1",
                         depth=0, run_id="t", extra_seeds=["LUZ-3"])
    assert {n.id for n in result.notes} == {"jira:LUZ-1", "jira:LUZ-3"}


def test_parse_input_extracts_seed_depth_repo_and_exclude():
    from knowledge_gathering.gather import parse_input
    assert parse_input('{"seed": "LUZ-1", "depth": 3, "repo": "ws/r"}') == ("LUZ-1", 3, "ws/r", None, False)
    assert parse_input("gather LUZ-1 depth 2 repo axonivy-prod/luz_docs_import") == \
        ("LUZ-1", 2, "axonivy-prod/luz_docs_import", None, False)
    assert parse_input("gather LUZ-1") == ("LUZ-1", 2, None, None, False)
    assert parse_input('{"seed": "LUZ-1", "exclude": "zip import"}') == ("LUZ-1", 2, None, "zip import", False)
    assert parse_input("gather LUZ-1 exclude zip import") == ("LUZ-1", 2, None, "zip import", False)


def test_parse_input_explore_flag_opts_into_noisy_tiers():
    """`explore` (default False) is the opt-in for the cloud/web/LLM discovery tiers — set by the
    client only after the user says Yes. Accepted via the JSON body and a plain `explore`/`deep` token."""
    from knowledge_gathering.gather import parse_input
    assert parse_input('{"seed": "LUZ-1", "explore": true}') == ("LUZ-1", 2, None, None, True)
    assert parse_input("gather LUZ-1 explore") == ("LUZ-1", 2, None, None, True)
    assert parse_input("gather LUZ-1 deep") == ("LUZ-1", 2, None, None, True)
    assert parse_input("gather LUZ-1") == ("LUZ-1", 2, None, None, False)  # default stays quiet


async def test_crawl_persists_index_and_runlog():
    bucket = FakeBucket()
    issues = {"LUZ-1": _issue("LUZ-1")}
    await crawl(FakeClient(issues), MemoryBank(bucket), "LUZ-1", depth=0, run_id="t")
    assert "memory/index/knowledge-index.json" in bucket.store
    assert any(k.startswith("memory/runs/") for k in bucket.store)
    assert "memory/notes/jira-issue/jira_LUZ-1.md" in bucket.store


def test_parse_input_malformed_json_yields_no_seed():
    """H2/M5: a truncated or ill-typed `{...}` body no longer raises out of the handler; it degrades to
    'no seed' (→ the friendly prompt) instead of a 500."""
    from knowledge_gathering.gather import parse_input
    assert parse_input('{"seed": "LUZ-1"') == (None, 2, None, None, False)          # truncated JSON
    assert parse_input('{"seed": "X", "depth": "two"}') == (None, 2, None, None, False)  # depth not an int


def test_exclude_ids_normalizes_keys_ids_and_urls():
    from knowledge_gathering.gather.domain import exclude_ids
    assert exclude_ids(None) == set()
    assert exclude_ids("  ") == set()
    assert exclude_ids("LUZ-999") == {"jira:LUZ-999"}
    assert exclude_ids("LUZ-1, 123456") == {"jira:LUZ-1", "confluence:123456"}


async def test_crawl_excludes_seed_and_links():
    """H2: excluded canonical ids are never fetched — neither as a start seed nor when reached via a
    link — while non-excluded siblings still follow."""
    issues = {"LUZ-1": _issue("LUZ-1", links_to=["LUZ-2", "LUZ-3"]),
              "LUZ-2": _issue("LUZ-2"), "LUZ-3": _issue("LUZ-3")}
    result = await crawl(FakeClient(issues), MemoryBank(FakeBucket()), "LUZ-1",
                         depth=2, run_id="t", exclude={"jira:LUZ-2"})
    ids = {n.id for n in result.notes}
    assert "jira:LUZ-2" not in ids
    assert {"jira:LUZ-1", "jira:LUZ-3"} <= ids

    only_seed = await crawl(FakeClient(issues), MemoryBank(FakeBucket()), "LUZ-1",
                            depth=0, run_id="t", exclude={"jira:LUZ-1"})
    assert only_seed.notes == []


async def test_over_budget_level_flags_dropped_as_gaps():
    """L10: nodes an under-budget level can't afford are surfaced as gaps, not dropped silently."""
    issues = {"LUZ-1": _issue("LUZ-1", links_to=["LUZ-2", "LUZ-3", "LUZ-4"]),
              "LUZ-2": _issue("LUZ-2"), "LUZ-3": _issue("LUZ-3"), "LUZ-4": _issue("LUZ-4")}
    result = await crawl(FakeClient(issues), MemoryBank(FakeBucket()), "LUZ-1",
                         depth=1, max_nodes=2, run_id="t")
    assert len(result.notes) == 2                       # seed + the one child we could afford
    assert len(result.gaps) == 2                        # the two we couldn't are flagged
    assert all(g.startswith("jira:") for g in result.gaps)


async def test_crawl_reraises_cancellation():
    """L11: a child CancelledError is propagated, not silently downgraded to a 'gap'."""
    class _Cancelling:
        base_url = BASE

        async def get_issue(self, key):
            raise asyncio.CancelledError

        async def get_issue_remote_links(self, key):
            return []

    with pytest.raises(asyncio.CancelledError):
        await crawl(_Cancelling(), MemoryBank(FakeBucket()), "LUZ-1", depth=0, run_id="t")
