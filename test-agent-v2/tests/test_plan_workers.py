"""Phase C — worker job build + result-path helpers + gate (pure, offline; pubsub imports are lazy)."""

from __future__ import annotations

import json

from test_plan_definition.implement.generate.workers import (
    build_job,
    enabled,
    handle_job,
    result_blob,
)


def test_build_job_carries_prompt_and_result_target():
    j = build_job("workers/ctx/run/2.txt", system="PACK", user="generate", max_tokens=16000)
    assert j == {"result_blob": "workers/ctx/run/2.txt", "system": "PACK",
                 "user": "generate", "max_tokens": 16000}
    json.dumps(j)  # must serialize for the Pub/Sub message body


def test_result_blob_is_keyed_by_ctx_run_batch():
    assert result_blob("run-abc", "r1", 3) == "workers/run-abc/r1/3.txt"


def test_enabled_gate(monkeypatch):
    monkeypatch.delenv("TPD_GEN_MODE", raising=False)
    assert enabled() is False
    monkeypatch.setenv("TPD_GEN_MODE", "workers")
    assert enabled() is True


def test_handle_job_writes_completed_text(monkeypatch):
    """Worker side: complete() the prompt, upload to the result blob. Both are faked — no net."""
    monkeypatch.setenv("GCS_BUCKET", "b")
    writes = {}

    class _Blob:
        def __init__(self, name): self.name = name
        def upload_from_string(self, s): writes[self.name] = s

    class _Bucket:
        def blob(self, name): return _Blob(name)

    class _Client:
        def bucket(self, name): return _Bucket()

    import common.adk.model as model
    monkeypatch.setattr(model, "complete", lambda prompt, **kw: "SCENARIO_JSON")
    import google.cloud.storage as storage
    monkeypatch.setattr(storage, "Client", lambda *a, **k: _Client())

    handle_job(json.dumps(build_job("workers/c/r/0.txt", system="S", user="U", max_tokens=100)).encode())
    assert writes == {"workers/c/r/0.txt": "SCENARIO_JSON"}
