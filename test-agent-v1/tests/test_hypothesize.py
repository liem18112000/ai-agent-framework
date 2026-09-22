"""G2 hypothesize step — `hypothesize_terms` (unit) + its wiring into `run_gather`.

No real Vertex: `complete` is monkeypatched in the hypothesize module to return canned JSON,
so the whole call path (flag gate, config select, parse, coerce, join) runs offline. The
run_gather test spies on `memory_self_seed` / `atlassian_search_seeds` to prove the enriched
terms reach G0/G1, and that a disabled gather makes ZERO LLM calls and behaves as before.
"""

from __future__ import annotations

import json
import types

import pytest

from knowledge_gathering.executor import gather as gather_mod
from knowledge_gathering.explore import expand as expand_mod
from knowledge_gathering.explore import hypothesize as hyp
from knowledge_gathering.loop import CrawlResult


@pytest.fixture
def vertex_on(monkeypatch):
    """Flag ON + Vertex configured — the state in which the single LLM call actually fires."""
    monkeypatch.setenv("KGA_LLM_HYPOTHESIZE", "1")
    monkeypatch.setenv("VERTEX_PROJECT", "p")
    monkeypatch.setenv("VERTEX_LOCATION", "us-east5")
    monkeypatch.setenv("VERTEX_MODEL", "claude-sonnet-5")


# --- hypothesize_terms unit --- #

def test_returns_union_terms_string(vertex_on, monkeypatch):
    canned = json.dumps({
        "key_phrases": ["restricted folder export"],
        "entities": ["Folder", "Document"],
        "subsystems": ["luz-docs", "export"],
    })
    monkeypatch.setattr(hyp, "complete", lambda *a, **k: canned)
    out = hyp.hypothesize_terms("Export fails for restricted folders", "a body", ["earchive"])
    # order-stable union of key_phrases + entities + subsystems
    assert out == "restricted folder export Folder Document luz-docs export"


def test_dedup_and_scalar_field_coercion(vertex_on, monkeypatch):
    # a repeated term is dropped; a scalar-typed field (entities as a str) is coerced to a list
    canned = json.dumps({"key_phrases": ["export", "export"], "entities": "Folder",
                         "subsystems": ["export"]})
    monkeypatch.setattr(hyp, "complete", lambda *a, **k: canned)
    assert hyp.hypothesize_terms("t") == "export Folder"


def test_tolerates_json_code_fence(vertex_on, monkeypatch):
    monkeypatch.setattr(hyp, "complete", lambda *a, **k: '```json\n{"entities":["Folder"]}\n```')
    assert hyp.hypothesize_terms("t") == "Folder"


@pytest.mark.parametrize("bad", ["not json at all", "{}", '{"key_phrases":[]}', '[{"a":1}]', ""])
def test_malformed_or_empty_json_returns_empty(vertex_on, monkeypatch, bad):
    monkeypatch.setattr(hyp, "complete", lambda *a, **k: bad)
    assert hyp.hypothesize_terms("Export fails") == ""  # → caller keeps raw terms


def test_llm_raises_returns_empty_never_propagates(vertex_on, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("vertex down")

    monkeypatch.setattr(hyp, "complete", boom)
    assert hyp.hypothesize_terms("Export fails") == ""


def test_flag_off_returns_empty_without_calling_llm(monkeypatch):
    monkeypatch.delenv("KGA_LLM_HYPOTHESIZE", raising=False)
    for k in ("VERTEX_PROJECT", "VERTEX_LOCATION", "VERTEX_MODEL"):
        monkeypatch.setenv(k, "x")
    calls = {"n": 0}

    def spy(*a, **k):
        calls["n"] += 1
        return "{}"

    monkeypatch.setattr(hyp, "complete", spy)
    assert hyp.hypothesize_terms("Export fails") == ""
    assert calls["n"] == 0  # flag off → ZERO LLM calls


def test_empty_title_returns_empty_without_calling_llm(vertex_on, monkeypatch):
    calls = {"n": 0}

    def spy(*a, **k):
        calls["n"] += 1
        return "{}"

    monkeypatch.setattr(hyp, "complete", spy)
    assert hyp.hypothesize_terms("   ") == ""
    assert calls["n"] == 0


def test_vertex_unconfigured_returns_empty_without_calling_llm(monkeypatch):
    monkeypatch.setenv("KGA_LLM_HYPOTHESIZE", "1")
    for k in ("VERTEX_PROJECT", "VERTEX_LOCATION", "VERTEX_MODEL"):
        monkeypatch.delenv(k, raising=False)
    calls = {"n": 0}

    def spy(*a, **k):
        calls["n"] += 1
        return "{}"

    monkeypatch.setattr(hyp, "complete", spy)
    assert hyp.hypothesize_terms("Export fails") == ""  # flag on but no Vertex → no call
    assert calls["n"] == 0


# --- run_gather wiring --- #

class _Ctx:
    context_id = "run-x"


class _IssueClient:
    """Returns one thin Jira issue (short body, no links/subtasks) → G1 fires."""

    def __init__(self, summary="Export fails for restricted folders", labels=("earchive",)):
        self._issue = {"fields": {
            "summary": summary,
            "description": {"type": "doc", "version": 1, "content": []},
            "issuelinks": [], "subtasks": [], "labels": list(labels), "components": [],
        }}

    async def get_issue(self, key):
        return self._issue


async def _run_gather(monkeypatch, *, flag_on, hyp_return="enriched export terms"):
    """Drive run_gather with G0/G1/crawl/reply stubbed; return what each phase observed."""
    seen = {"hyp_calls": 0, "self_seed_terms": None, "search_terms": None, "reply": None}

    def fake_hyp(title, description="", labels=None):
        seen["hyp_calls"] += 1
        return hyp_return

    def fake_self_seed(bank, seed, terms=""):
        seen["self_seed_terms"] = terms
        return [], ""

    async def fake_search(client, terms, *, project=None, exclude=None, **kw):
        seen["search_terms"] = terms
        return [], ""

    async def fake_crawl(*a, **k):
        return CrawlResult()

    async def fake_reply(context, event_queue, text):
        seen["reply"] = text

    monkeypatch.setattr(expand_mod, "hypothesize_terms", fake_hyp)
    monkeypatch.setattr(expand_mod, "memory_self_seed", fake_self_seed)
    monkeypatch.setattr(expand_mod, "atlassian_search_seeds", fake_search)
    monkeypatch.setattr(gather_mod, "crawl", fake_crawl)
    monkeypatch.setattr(gather_mod, "reply", fake_reply)
    if flag_on:
        monkeypatch.setenv("KGA_LLM_HYPOTHESIZE", "1")
    else:
        monkeypatch.delenv("KGA_LLM_HYPOTHESIZE", raising=False)

    ex = types.SimpleNamespace(_client=_IssueClient(), _bank=object(), _distiller=None)
    await gather_mod.run_gather(ex, _Ctx(), object(), "gather LUZ-158390 depth 1")
    return seen


async def test_flag_off_no_llm_call_and_raw_terms_flow(monkeypatch):
    seen = await _run_gather(monkeypatch, flag_on=False)
    assert seen["hyp_calls"] == 0  # disabled → not even the thread offload
    # G0 + G1 (thin) both receive the RAW probe terms, exactly as before G2 existed
    assert "Export fails" in seen["self_seed_terms"] and "earchive" in seen["self_seed_terms"]
    assert seen["search_terms"] == seen["self_seed_terms"]
    assert "enriched" not in (seen["self_seed_terms"] or "")
    assert "Hypothesized focus" not in seen["reply"]


async def test_flag_on_enriched_terms_reach_g0_and_g1(monkeypatch):
    seen = await _run_gather(monkeypatch, flag_on=True)
    assert seen["hyp_calls"] == 1  # exactly one hypothesize (one LLM call) per gather
    # the enriched terms REPLACE the raw ones into both G0 self-seed and G1 search
    assert seen["self_seed_terms"] == "enriched export terms"
    assert seen["search_terms"] == "enriched export terms"
    assert "Hypothesized focus: enriched export terms" in seen["reply"]


async def test_flag_on_but_empty_hyp_keeps_raw_terms(monkeypatch):
    # LLM returned junk → hypothesize_terms yields "" → caller falls back to raw probe terms
    seen = await _run_gather(monkeypatch, flag_on=True, hyp_return="")
    assert seen["hyp_calls"] == 1
    assert "Export fails" in seen["self_seed_terms"]  # raw terms, not the enriched string
    assert "Hypothesized focus" not in seen["reply"]
