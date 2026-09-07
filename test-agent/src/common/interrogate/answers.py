"""Ingest human answers to a question set.

Accepts JSON (a list of answer dicts, `{question_id: value}`, or `{"answers": [...]}`)
or plain `Q-id: value` lines. Matches each to a question, records the choice, and
tracks what was answered / carried (still open) / deferred — nothing is dropped.
A `[seed:<node>]` marker in an answer re-seeds gathering.
"""

from __future__ import annotations

import json
import re

from common.models import Answer, IngestResult, Question

_SEED_RE = re.compile(r"\[seed:([^\]]+)\]")
_DEFER = {"defer", "deferred", "skip", "later", "n/a", "na"}


def parse_raw_answers(raw) -> dict:
    """Normalize any accepted input to `{question_id: value}` (value = str or dict)."""
    if isinstance(raw, dict):
        if isinstance(raw.get("answers"), list):
            return {a["question_id"]: a for a in raw["answers"]}
        return dict(raw)
    if isinstance(raw, list):
        return {a["question_id"]: a for a in raw}
    text = str(raw).strip()
    if text.startswith(("{", "[")):
        return parse_raw_answers(json.loads(text))
    out: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, val = line.partition(":")
        if sep and key.strip():
            out[key.strip()] = val.strip()
    return out


def _coerce(value) -> tuple[str, str, str | None]:
    """→ (chosen_option, text, new_seed)."""
    if isinstance(value, dict):
        text = value.get("text") or value.get("answer") or ""
        return value.get("chosen_option", ""), text, value.get("new_seed")
    text = str(value).strip()
    seed = None
    if m := _SEED_RE.search(text):
        seed, text = m.group(1).strip(), _SEED_RE.sub("", text).strip()
    return "", text, seed


def _match_option(text: str, options: list[dict]) -> str:
    low = text.lower()
    for opt in options:
        label = opt.get("label", "")
        if label and (label.lower() in low or low in label.lower()):
            return label
    return ""


def ingest(questions: list[Question], raw, *, now: str = "", answered_by: str = "human") -> IngestResult:
    values = parse_raw_answers(raw)
    by_id = {q.id: q for q in questions}
    result = IngestResult()
    for qid, value in values.items():
        q = by_id.get(qid)
        if q is None:
            continue  # answer to an unknown question id — ignore
        chosen, text, seed = _coerce(value)
        if text.lower() in _DEFER and not seed:
            q.status = "deferred"
            result.deferred.append(q)
            continue
        if not chosen:
            chosen = _match_option(text, q.options)
        q.status = "answered"
        result.answers.append(Answer(
            question_id=qid, answered_by=answered_by, chosen_option=chosen,
            text=text, answered_at=now, new_seed=seed,
        ))
        result.answered.append(q)
    answered_ids = {a.question_id for a in result.answers}
    result.carried = [q for q in questions if q.status == "open" and q.id not in answered_ids]
    return result
