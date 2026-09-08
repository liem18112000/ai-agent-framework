"""M3 tests: the bounded frontier crawl (dedup, budget, gaps, record-only)."""

from __future__ import annotations

from google.api_core.exceptions import PreconditionFailed

from common.memory import MemoryBank
from knowledge_gathering.loop import crawl, normalize_seed

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
            raise PreconditionFailed("gen mismatch")
        self._b.store[self.name] = data
        self._b.gens[self.name] = cur + 1


class FakeBucket:
    def __init__(self):
        self.store, self.gens = {}, {}

    def blob(self, name):
        return FakeBlob(self, name)

    def get_blob(self, name):
        return FakeBlob(self, name) if name in self.store else None


def _issue(key, links_to=(), bitbucket=False):
    content = []
    for lk in links_to:
        pass
    if bitbucket:
        content.append({"type": "paragraph", "content": [
            {"type": "inlineCard", "attrs": {"url": "https://bitbucket.org/acme/r/src/main/F.java"}}]})
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


async def test_extra_seeds_are_crawled_at_depth_zero():
    issues = {"LUZ-1": _issue("LUZ-1"), "LUZ-3": _issue("LUZ-3")}
    result = await crawl(FakeClient(issues), MemoryBank(FakeBucket()), "LUZ-1",
                         depth=0, run_id="t", extra_seeds=["LUZ-3"])
    assert {n.id for n in result.notes} == {"jira:LUZ-1", "jira:LUZ-3"}


def test_parse_input_extracts_seed_depth_repo_and_exclude():
    from knowledge_gathering.gather import parse_input
    assert parse_input('{"seed": "LUZ-1", "depth": 3, "repo": "ws/r"}') == ("LUZ-1", 3, "ws/r", None)
    assert parse_input("gather LUZ-1 depth 2 repo axonivy-prod/luz_docs_import") == \
        ("LUZ-1", 2, "axonivy-prod/luz_docs_import", None)
    assert parse_input("gather LUZ-1") == ("LUZ-1", 2, None, None)
    assert parse_input('{"seed": "LUZ-1", "exclude": "zip import"}') == ("LUZ-1", 2, None, "zip import")
    assert parse_input("gather LUZ-1 exclude zip import") == ("LUZ-1", 2, None, "zip import")


async def test_crawl_persists_index_and_runlog():
    bucket = FakeBucket()
    issues = {"LUZ-1": _issue("LUZ-1")}
    await crawl(FakeClient(issues), MemoryBank(bucket), "LUZ-1", depth=0, run_id="t")
    assert "memory/index/knowledge-index.json" in bucket.store
    assert any(k.startswith("memory/runs/") for k in bucket.store)
    assert "memory/notes/jira-issue/jira_LUZ-1.md" in bucket.store
