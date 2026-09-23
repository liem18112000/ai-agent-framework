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
    """Worker side: complete() the prompt, upload to the result blob via the ObjectStore. Faked — no net."""
    import common.adk.model as model
    import common.store as store_mod
    from common.store.memory import InMemoryObjectStore

    monkeypatch.setattr(model, "complete", lambda prompt, **kw: "SCENARIO_JSON")
    store = InMemoryObjectStore()
    monkeypatch.setattr(store_mod, "build_object_store", lambda: store)

    handle_job(json.dumps(build_job("workers/c/r/0.txt", system="S", user="U", max_tokens=100)).encode())
    assert store.get_blob("workers/c/r/0.txt").download_as_text() == "SCENARIO_JSON"
