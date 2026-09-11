"""Ingest human answers to a question set."""

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
    return {
        key.strip(): val.strip()
        for line in text.splitlines()
        for key, sep, val in [line.partition(":")]
        if sep and key.strip()
    }


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

    def present(label: str) -> bool:
        # label appears as a standalone run in the answer (so 2-char "ui" ≠ b*ui*ld / s*ui*te),
        # or a short answer is a substring of the label (e.g. "rest" in "api (rest)").
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(label)}(?![a-z0-9])", low)) or low in label

    return next((o["label"] for o in options if o.get("label") and present(o["label"].lower())), "")


def ingest(questions: list[Question], raw, *, now: str = "", answered_by: str = "human") -> IngestResult:
    values = parse_raw_answers(raw)
    by_id = {q.id: q for q in questions}
    result = IngestResult()
    for qid, value in values.items():
        q = by_id.get(qid)
        if q is None:
            continue
        chosen, text, seed = _coerce(value)
        if text.lower() in _DEFER and not seed:
            q.status = "deferred"
            result.deferred.append(q)
            continue
        if not chosen:
            chosen = _match_option(text, q.options)
        q.status = "answered"
        result.answers.append(Answer(question_id=qid, answered_by=answered_by, chosen_option=chosen, text=text, answered_at=now, new_seed=seed))
        result.answered.append(q)
    answered_ids = {a.question_id for a in result.answers}
    result.carried = [q for q in questions if q.status == "open" and q.id not in answered_ids]
    return result
