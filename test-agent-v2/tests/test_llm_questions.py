"""ADK-03 — `_parse` per-item robustness: skip malformed items, drop None optionals."""

from __future__ import annotations

import json

from common.llm.questions import _parse


def test_parse_skips_bad_item_and_keeps_good():
    raw = json.dumps([
        {"id": "Q-1", "question": "What is the done bar?", "why": "scope"},
        {"why": "no id and no question — malformed"},
    ])
    qs = _parse(raw, "business")
    assert len(qs) == 1
    assert qs[0].id == "Q-1"
    assert qs[0].round == "business"


def test_parse_null_options_becomes_empty_list():
    raw = json.dumps([{"id": "Q-2", "question": "Which env?", "options": None}])
    qs = _parse(raw, "qa")
    assert len(qs) == 1
    assert qs[0].options == []
