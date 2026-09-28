"""Token-optimization guards: the meter counts, and the prompts stop re-sending the pack.

Each case pins one saving that is invisible at runtime — a duplicated pack still produces a correct
answer, a cache prefix that never matches still returns text. Only the token bill notices, so
without these the regressions come back silently.
"""

from __future__ import annotations

import pytest

from common.llm import meter
from common.models import Note, Pack
from common.testplan.llm.prompts import scope_classify_prompt
from common.testplan.models import PlanPack, TestPlan


@pytest.fixture(autouse=True)
def _clean_meter():
    meter.reset()
    yield
    meter.reset()


class _Usage:
    """Stands in for an Anthropic `message.usage`."""

    input_tokens = 100
    output_tokens = 20
    cache_read_input_tokens = 900
    cache_creation_input_tokens = 0


def test_meter_accumulates_per_label_and_total():
    meter.record_message("define.brief", _Usage())
    meter.record("implement.gen", input=50, output=10, cache_write=800)

    snap = meter.snapshot()
    assert snap["define.brief"]["cache_read"] == 900
    assert snap["implement.gen"]["cache_write"] == 800
    assert snap["TOTAL"] == {"calls": 2, "input": 150, "output": 30,
                             "cache_read": 900, "cache_write": 800}
    assert "cache-hit=53%" in meter.summary_line()  # 900 read / 1700 cached


def test_meter_tolerates_a_missing_usage_block():
    meter.record_message("nothing", None)
    assert meter.snapshot()["TOTAL"]["calls"] == 0


def _plan_pack(marker: str) -> tuple[TestPlan, PlanPack]:
    notes = [Note(id="jira:X-1", type="jira", title="Upload a zip", synopsis=marker),
             Note(id="jira:X-2", type="jira", title="Reject a bomb", synopsis=marker)]
    plan = TestPlan(id="plan:1", context_id="ctx", methodology=["API"], scope=["jira:X-1"])
    return plan, PlanPack(pack=Pack(context_id="ctx", notes=notes), understanding="the feature")


def test_scope_classifier_does_not_inline_the_pack():
    """`classify_in_scope` already sends the pack as the agent's cached system instruction, so the
    user prompt must not carry a second copy."""
    # The listing truncates each synopsis at 160 chars, so a marker placed AFTER that point can only
    # reach the prompt via the full pack dump — which is exactly what must be gone.
    tail = "ONLY-IN-THE-FULL-PACK-DUMP"
    plan, plan_pack = _plan_pack("x" * 300 + tail)
    summary = plan_pack.summary_text()
    assert tail in summary  # the pack itself does carry it

    prompt = scope_classify_prompt(plan, summary, plan_pack.pack.grounded,
                                   understanding=plan_pack.understanding)

    assert tail not in prompt
    assert "Context pack:" not in prompt
    assert "jira:X-1" in prompt  # the id->title listing survives — that IS the classifier's menu


def test_refine_understanding_shares_the_questions_cache_prefix():
    """Both calls in a refine pass must pass a BYTE-IDENTICAL `cache_prefix`, or neither reads the
    other's cache entry and the pack is billed twice at the 2x write rate."""
    from common.llm.prompts import question_prompt, understanding_prompt

    pack = Pack(context_id="ctx", notes=[
        Note(id="jira:X-1", type="jira", title="Upload", synopsis="s" * 500)])

    body = understanding_prompt(pack, [], [], "medium", [], include_context=False)
    assert "Context pack:" not in body
    assert pack.summary_text() not in body

    # question_prompt's cache_prefix (common/llm/questions.py) is pack.summary_text() verbatim;
    # understanding.py must pass the same expression, not a wrapped/headed variant.
    assert question_prompt(pack, "business", include_context=False).count("Context pack:") == 0

    with_ctx = understanding_prompt(pack, [], [], "medium", [], include_context=True)
    assert pack.summary_text() in with_ctx  # the no-cache path still carries the pack


def test_recorded_insights_do_not_drift_the_cached_prefix(fake_bucket):
    """The silent invalidator this whole design is exposed to.

    The cache prefix is `Pack.summary_text()`, and that renders an "Already decided (existing
    insights)" section when the pack carries INSIGHT notes. Insights are recorded round by round, so
    if they reached the pack the prefix would change on EVERY round — byte-different, zero cache
    reads, and no error anywhere. `load_pack` filters INSIGHT nodes out of `notes`, which is the only
    thing keeping the prefix stable; this pins that filter."""
    from common.interrogate.pack import load_pack
    from common.memory import MemoryBank
    from common.models.refine import INSIGHT

    bank = MemoryBank(fake_bucket)
    grounded = Note(id="jira:X-1", type="jira", title="Upload", synopsis="s" * 500, run_id="ctx")
    bank.upsert_note(grounded)
    bank.update_index(lambda g: g.add_note(grounded))
    before = load_pack(bank, "ctx").summary_text()

    # a round completes and records its decision into the same bank
    insight = Note(id="insight:1", type=INSIGHT, title="decided: API only", run_id="ctx")
    bank.upsert_note(insight)
    bank.update_index(lambda g: g.add_note(insight))
    after = load_pack(bank, "ctx").summary_text()

    assert after == before, "prefix drifted between rounds — every later round is a cache MISS"
    assert "Already decided" not in after


def test_distill_reuses_the_banked_synopsis_for_an_unchanged_body():
    """A re-gather of an unchanged node must not pay for a second distillation."""
    from knowledge_gathering.gather.crawl.crawl import _cached_distill

    calls = []

    def distiller(note, text):
        calls.append(note.id)
        return "fresh synopsis"

    class _Bank:
        def __init__(self, prior):
            self.prior = prior

        def read_note(self, note_id, note_type):
            return self.prior

    banked = Note(id="jira:X-1", type="jira", title="Upload", body="BODY", synopsis="banked")
    fresh = Note(id="jira:X-1", type="jira", title="Upload", body="BODY")

    assert _cached_distill(_Bank(banked), distiller, fresh, "BODY") == "banked"
    assert calls == []  # the whole point: no LLM call

    changed = Note(id="jira:X-1", type="jira", title="Upload", body="BODY v2")
    assert _cached_distill(_Bank(banked), distiller, changed, "BODY v2") == "fresh synopsis"
    assert calls == ["jira:X-1"]  # edited upstream -> re-distilled

    assert _cached_distill(_Bank(None), distiller, fresh, "BODY") == "fresh synopsis"  # first gather


def test_distill_cache_survives_an_unreadable_bank():
    from knowledge_gathering.gather.crawl.crawl import _cached_distill

    class _Broken:
        def read_note(self, note_id, note_type):
            raise RuntimeError("GCS is down")

    note = Note(id="jira:X-1", type="jira", title="Upload", body="BODY")
    assert _cached_distill(_Broken(), lambda n, t: "fresh", note, "BODY") == "fresh"


def _litellm_kwargs(monkeypatch, **env) -> dict:
    """The kwargs the provider hands to `LiteLlm` — the only place the ADK path's cache config is
    observable offline (no request is ever built)."""
    import google.adk.models.lite_llm as adk_lite_llm

    from common.adk.providers.vertex_claude import VertexClaudeProvider

    for k, v in {"VERTEX_PROJECT": "p", "VERTEX_LOCATION": "global",
                 "VERTEX_MODEL": "claude-sonnet-5", **env}.items():
        monkeypatch.setenv(k, v)

    captured: dict = {}
    monkeypatch.setattr(adk_lite_llm, "LiteLlm", lambda **kw: captured.update(kw))
    VertexClaudeProvider().llm_agent_model()
    return captured


def test_adk_injection_point_states_the_ttl_explicitly(monkeypatch):
    """litellm resolves `point.get("control") or ChatCompletionCachedContent(type="ephemeral")`, so an
    injection point WITHOUT `control` silently runs the 5-minute TTL — the default that expires
    mid-implement-round. The TTL must be stated, and must match the direct path's constant."""
    from common.llm.vertex import _CACHE_TTL

    points = _litellm_kwargs(monkeypatch)["cache_control_injection_points"]

    assert len(points) == 1, "only the system message is stable across our single-turn generators"
    assert points[0]["role"] == "system"
    assert points[0]["control"] == {"type": "ephemeral", "ttl": _CACHE_TTL}


def test_adk_cache_can_be_switched_off(monkeypatch):
    assert "cache_control_injection_points" not in _litellm_kwargs(monkeypatch, TPD_ADK_CACHE="0")


def test_cache_prefix_uses_the_one_hour_ttl():
    """The 5-minute default expires between human-paced define rounds, so every round re-paid the
    write and never read. Pin the 1h TTL and the block ordering (cached prefix must come first)."""
    from common.llm.vertex import _user_content

    blocks = _user_content("the task", "x" * 9000)
    assert blocks[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert blocks[0]["text"].startswith("x")   # prefix first, or the match window starts too late
    assert blocks[1]["text"] == "the task"
    assert _user_content("the task", None) == "the task"  # no prefix -> no cache block at all
