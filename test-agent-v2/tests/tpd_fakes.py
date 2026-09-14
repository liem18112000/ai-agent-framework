"""Offline fakes for the TPD implement ``LlmAgent``s.

A ``BaseLlm`` test double that returns canned structured JSON (matched to each generator by a
substring of its prompt) and counts every model turn — this call counter is what the call-count
tests assert (assured always-on: default implement = 2 calls = generate + judge; ``detail`` = 4).
Inject it via ``implement_plan(..., model=…)`` or ``generate_scenarios(..., model=…)`` so the
generators never touch the real Vertex network.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import Field


def _request_text(llm_request) -> str:
    """All prompt text in an ``LlmRequest`` (system instruction + contents), for routing."""
    parts: list[str] = []
    cfg = getattr(llm_request, "config", None)
    si = getattr(cfg, "system_instruction", None) if cfg else None
    if isinstance(si, str):
        parts.append(si)
    elif si is not None:
        for p in getattr(si, "parts", None) or []:
            if getattr(p, "text", None):
                parts.append(p.text)
    for c in getattr(llm_request, "contents", None) or []:
        for p in getattr(c, "parts", None) or []:
            if getattr(p, "text", None):
                parts.append(p.text)
    return "\n".join(parts)


class FakeGeneratorModel(BaseLlm):
    """Routes canned JSON by the generator prompt; counts every model turn (the I3 gate).

    The P4 judge ('QA CRITIC' marker) is routed FIRST and counted in ``judge_calls``; set
    ``judge_queue`` to script one verdict per judge turn (reflexion tests), else ``judge_json`` is
    reused. Every prompt is recorded in ``seen`` so a test can assert reflections threaded through."""

    calls: int = 0
    judge_calls: int = 0
    scenarios_json: str = '{"items": []}'
    testdata_json: str = '{"items": []}'
    steps_json: str = '{"items": []}'
    judge_json: str = "{}"
    judge_queue: list[str] = Field(default_factory=list)
    seen: list[str] = Field(default_factory=list)
    default_json: str = "{}"
    delay_s: float = 0.0  # stall each turn (to exercise run_json_agent's per-call timeout)

    async def generate_content_async(
        self, llm_request, stream: bool = False,
    ) -> AsyncGenerator[LlmResponse, None]:
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        self.calls += 1
        text = _request_text(llm_request)
        self.seen.append(text)
        if "QA CRITIC" in text:
            self.judge_calls += 1
            canned = self.judge_queue.pop(0) if self.judge_queue else self.judge_json
        elif "TEST SCENARIOS" in text:
            canned = self.scenarios_json
        elif "TEST DATA" in text:
            canned = self.testdata_json
        elif "STEP-BY-STEP" in text:
            canned = self.steps_json
        else:
            canned = self.default_json
        yield LlmResponse(
            content=types.Content(role="model", parts=[types.Part(text=canned)]),
            partial=False,
        )


# --- canned payloads ---------------------------------------------------------------------------

def scenarios_json(items: list[dict]) -> str:
    return json.dumps({"items": items})


def testdata_json(items: list[dict]) -> str:
    return json.dumps({"items": items})


def steps_json(items: list[dict]) -> str:
    return json.dumps({"items": items})


def judge_verdict(overall: float, *, accept: bool | None = None,
                  reflections: list[str] | None = None, issues: list[str] | None = None) -> str:
    """A canned P4 JudgeVerdict payload; ``accept`` defaults to ``overall >= 0.7``."""
    return json.dumps({"overall": overall,
                       "accept": overall >= 0.7 if accept is None else accept,
                       "reflections": reflections or [], "issues": issues or []})


_DEFAULT_SCENARIOS = [
    {"id": "scenario:run-6f2a:a", "title": "A happy", "kind": "happy",
     "methodology": "api", "description": "verifies A", "rationale": "A matters",
     "source_refs": ["jira:LUZ-158390"]},
    {"id": "scenario:run-6f2a:b", "title": "B negative", "kind": "negative",
     "methodology": "api", "description": "verifies B", "rationale": "B matters",
     "source_refs": ["jira:LUZ-158390"]},
]
_DEFAULT_TESTDATA = [
    {"id": "test-data:run-6f2a:account", "kind": "test-account",
     "spec": {"role": "standard"}, "source_refs": ["jira:LUZ-158390"]},
]
_DEFAULT_STEPS = [
    {"scenario_id": "scenario:run-6f2a:a",
     "steps": [{"order": 1, "keyword": "Given", "action": "prep", "expected": "ready"},
               {"order": 2, "keyword": "When", "action": "send request", "expected": "2xx"},
               {"order": 3, "keyword": "Then", "action": "assert", "expected": "ok"}]},
    {"scenario_id": "scenario:run-6f2a:b",
     "steps": [{"order": 1, "keyword": "Given", "action": "prep", "expected": "ready"},
               {"order": 2, "keyword": "When", "action": "send request", "expected": "4xx"}]},
]


def full_fake_model() -> FakeGeneratorModel:
    """A fake configured with valid canned output for all three generators + an accepting judge
    (so the always-on assured loop passes on round 1 with this fake)."""
    return FakeGeneratorModel(
        model="fake",
        scenarios_json=scenarios_json(_DEFAULT_SCENARIOS),
        testdata_json=testdata_json(_DEFAULT_TESTDATA),
        steps_json=steps_json(_DEFAULT_STEPS),
        judge_json=judge_verdict(0.9),
    )
