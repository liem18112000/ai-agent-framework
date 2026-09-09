"""MemoryBank — GCS notes (json sidecar + rendered md), a link-graph index"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import asdict

from google.api_core.exceptions import PreconditionFailed

from common.memory.render import (
    render_index_md,
    render_insight_md,
    render_note_md,
    render_refine_run_log_md,
    render_run_log_md,
)
from common.memory.serialize import (
    answer_from_dict,
    insight_from_dict,
    merge_notes,
    note_from_dict,
    question_from_dict,
)
from common.models import (
    INSIGHT,
    Answer,
    Graph,
    Insight,
    Note,
    Question,
    RefinementRun,
    RunLog,
)
from common.monitoring import get_logger

log = get_logger("memory.bank")

ROOT = "memory"
INDEX_JSON = f"{ROOT}/index/knowledge-index.json"
INDEX_MD = f"{ROOT}/index/knowledge-index.md"


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_")


class MemoryBank:
    def __init__(self, bucket, *, redactor: Callable[[str], str] | None = None, on_write=None) -> None:
        self._bucket = bucket
        self._redact = redactor or (lambda s: s)
        self.on_write = on_write

    def _fire_on_write(self, node_id: str, node_type: str, kind: str) -> None:
        if self.on_write is None:
            return
        try:
            self.on_write(self, node_id, node_type, kind)
        except Exception as exc:  # noqa: BLE001 — projection is best-effort; GCS stays the truth
            log.warning("memory: on_write hook failed for %s (%s)", node_id, exc)

    def _note_json(self, note_type: str, note_id: str) -> str:
        return f"{ROOT}/notes/{note_type}/{_slug(note_id)}.json"

    def _note_md(self, note_type: str, note_id: str) -> str:
        return f"{ROOT}/notes/{note_type}/{_slug(note_id)}.md"

    def _put(self, path: str, data: str, ctype: str, **kw) -> None:
        self._bucket.blob(path).upload_from_string(data, content_type=ctype, **kw)

    def put_json(self, path: str, obj) -> str:
        self._put(path, json.dumps(obj, indent=1, ensure_ascii=False), "application/json")
        return path

    def get_json(self, path: str, default=None):
        return self._read_json(path, default)

    def put_text(self, path: str, text: str) -> str:
        self._put(path, self._redact(text), "text/markdown")
        return path

    def get_text(self, path: str) -> str | None:
        blob = self._bucket.get_blob(path)
        return blob.download_as_text() if blob else None

    def read_note(self, note_id: str, note_type: str) -> Note | None:
        blob = self._bucket.get_blob(self._note_json(note_type, note_id))
        return note_from_dict(json.loads(blob.download_as_text())) if blob else None

    def read_note_md(self, note_id: str, note_type: str) -> str | None:
        blob = self._bucket.get_blob(self._note_md(note_type, note_id))
        return blob.download_as_text() if blob else None

    def upsert_note(self, note: Note) -> str:
        existing = self.read_note(note.id, note.type)
        merged = merge_notes(existing, note) if existing else note
        self._put(self._note_json(note.type, note.id), json.dumps(asdict(merged), indent=1, ensure_ascii=False), "application/json")
        path = self._note_md(note.type, note.id)
        self._put(path, self._redact(render_note_md(merged)), "text/markdown")
        self._fire_on_write(merged.id, merged.type, "")
        return path

    def load_index(self) -> tuple[Graph, int]:
        blob = self._bucket.get_blob(INDEX_JSON)
        return (Graph(), 0) if blob is None else (Graph.from_json(json.loads(blob.download_as_text())), blob.generation)

    def update_index(self, mutate: Callable[[Graph], None], *, max_retries: int = 5) -> Graph:
        for _ in range(max_retries):
            graph, generation = self.load_index()
            mutate(graph)
            try:
                self._put(INDEX_JSON, json.dumps(graph.to_json(), indent=1, ensure_ascii=False), "application/json", if_generation_match=generation)
            except PreconditionFailed:
                continue
            self._put(INDEX_MD, self._redact(render_index_md(graph)), "text/markdown")
            return graph
        raise RuntimeError("index CAS retries exhausted")

    def mutate_json(self, path: str, mutate: Callable[[object], object], *, default, max_retries: int = 5):
        """CAS a JSON blob at `path` (generalises `update_index`'s retry loop for any shape)."""
        for _ in range(max_retries):
            blob = self._bucket.get_blob(path)
            current = json.loads(blob.download_as_text()) if blob else default
            generation = blob.generation if blob else 0
            new = mutate(current)
            try:
                self._put(path, json.dumps(new, indent=1, ensure_ascii=False), "application/json", if_generation_match=generation)
            except PreconditionFailed:
                continue
            return new
        raise RuntimeError(f"mutate_json CAS retries exhausted for {path}")

    def append_run_log(self, run: RunLog) -> str:
        path = f"{ROOT}/runs/{_slug(run.started) or run.run_id}_run-{run.run_id}.md"
        self._put(path, self._redact(render_run_log_md(run)), "text/markdown")
        return path

    def _read_json(self, path: str, default):
        blob = self._bucket.get_blob(path)
        return json.loads(blob.download_as_text()) if blob else default

    def _refine_dir(self, context_id: str) -> str:
        return f"{ROOT}/refine/{_slug(context_id)}"

    def upsert_insight(self, insight: Insight) -> str:
        """Write an insight note (json sidecar + rendered md). Index update is batched by the caller."""
        self._put(self._note_json(INSIGHT, insight.id), json.dumps(asdict(insight), indent=1, ensure_ascii=False), "application/json")
        path = self._note_md(INSIGHT, insight.id)
        self._put(path, self._redact(render_insight_md(insight)), "text/markdown")
        self._fire_on_write(insight.id, INSIGHT, insight.kind)
        return path

    def read_insight(self, insight_id: str) -> Insight | None:
        d = self._read_json(self._note_json(INSIGHT, insight_id), None)
        return insight_from_dict(d) if d else None

    def write_questions(self, context_id: str, questions: list[Question]) -> str:
        path = f"{self._refine_dir(context_id)}/questions.json"
        self._put(path, json.dumps([asdict(q) for q in questions], indent=1, ensure_ascii=False), "application/json")
        return path

    def read_questions(self, context_id: str) -> list[Question]:
        return [question_from_dict(d) for d in self._read_json(f"{self._refine_dir(context_id)}/questions.json", [])]

    def append_answers(self, context_id: str, answers: list[Answer]) -> str:
        path = f"{self._refine_dir(context_id)}/answers.json"
        existing = self._read_json(path, [])
        existing.extend(asdict(a) for a in answers)
        self._put(path, json.dumps(existing, indent=1, ensure_ascii=False), "application/json")
        return path

    def read_answers(self, context_id: str) -> list[Answer]:
        return [answer_from_dict(d) for d in self._read_json(f"{self._refine_dir(context_id)}/answers.json", [])]

    def write_understanding(self, context_id: str, md: str) -> str:
        path = f"{self._refine_dir(context_id)}/understanding.md"
        self._put(path, self._redact(md), "text/markdown")
        return path

    def read_understanding(self, context_id: str) -> str | None:
        blob = self._bucket.get_blob(f"{self._refine_dir(context_id)}/understanding.md")
        return blob.download_as_text() if blob else None

    def append_refine_run_log(self, run: RefinementRun) -> str:
        path = f"{ROOT}/runs/{_slug(run.started) or run.run_id}_refine-{run.run_id}.md"
        self._put(path, self._redact(render_refine_run_log_md(run)), "text/markdown")
        return path

    def write_refine_state(self, context_id: str, state: dict) -> str:
        path = f"{self._refine_dir(context_id)}/state.json"
        self._put(path, json.dumps(state, indent=1, ensure_ascii=False), "application/json")
        return path

    def read_refine_state(self, context_id: str) -> dict:
        return self._read_json(f"{self._refine_dir(context_id)}/state.json", {})

    def link_session(self, a2a_context_id: str, pack_context_id: str) -> None:
        """Map an A2A conversation id → the pack context_id it is refining."""
        self._put(f"{ROOT}/refine/_sessions/{_slug(a2a_context_id)}.json", json.dumps({"pack_context_id": pack_context_id}), "application/json")

    def resolve_session(self, a2a_context_id: str) -> str | None:
        d = self._read_json(f"{ROOT}/refine/_sessions/{_slug(a2a_context_id)}.json", None)
        return d.get("pack_context_id") if d else None
