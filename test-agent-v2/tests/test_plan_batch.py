"""Phase B — Vertex Claude batch request builder + output parser (pure, offline).

The live submit/poll (`_submit_and_collect`) is a preview API and is not offline-testable; these cover
the parts that must be exactly right: the JSONL request envelope and the output-JSONL parsing.
"""

from __future__ import annotations

import json

from test_plan_definition.implement.generate.batch import build_request, enabled, parse_output


def test_build_request_is_the_vertex_claude_batch_envelope():
    r = build_request("batch-2", system="PACK", user="make scenarios", max_tokens=16000)
    assert r["custom_id"] == "batch-2"
    req = r["request"]
    assert req["anthropic_version"] == "vertex-2023-10-16"  # pinned by the Vertex batch schema
    assert req["max_tokens"] == 16000
    assert req["thinking"] == {"type": "disabled"}
    assert req["system"][0]["text"] == "PACK"
    assert req["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert req["messages"] == [{"role": "user", "content": "make scenarios"}]
    json.dumps(r)  # must be JSON-serializable for the JSONL upload


def test_parse_output_handles_top_level_and_nested_and_junk():
    top = json.dumps({"custom_id": "batch-0", "content": [{"type": "text", "text": "A"}]})
    nested = json.dumps({"custom_id": "batch-1",
                         "response": {"body": {"content": [{"type": "text", "text": "B"}]}}})
    out = parse_output("\n".join([top, nested, "not json", ""]))
    assert out == {"batch-0": "A", "batch-1": "B"}


def test_enabled_gate(monkeypatch):
    monkeypatch.delenv("TPD_BATCH_MODE", raising=False)
    assert enabled() is False
    monkeypatch.setenv("TPD_BATCH_MODE", "vertex_batch")
    assert enabled() is True
