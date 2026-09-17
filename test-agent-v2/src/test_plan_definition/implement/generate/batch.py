"""Phase B — Vertex Claude Batch API path for scenario generation (async, provider-managed fan-out).

Submit ALL generation batches as ONE Vertex batch-prediction job over Claude (Anthropic Message Batches
on Vertex): input JSONL in GCS, the provider fans the requests out in parallel (~<1h, 50% cheaper), the
output JSONL is read back and parsed into scenarios. Gated by ``TPD_BATCH_MODE=vertex_batch``; the default
is the synchronous per-batch path in ``llm.py``.

WHAT'S VERIFIED vs NOT:
- `AnthropicVertex` exposes NO batch API, so this uses `google-cloud-aiplatform` `BatchPredictionJob`
  against the publisher model `publishers/anthropic/models/<id>`.
- Input line format (verified from the Vertex Claude batch docs):
  ``{"custom_id": "...", "request": {"anthropic_version": "vertex-2023-10-16", "messages": [...], "max_tokens": N}}``
- ``build_request`` + ``parse_output`` are pure and UNIT-TESTED.
- The submit/poll/collect path (`_submit_and_collect`) is a PREVIEW API and is NOT offline-testable — it is
  best-effort: ANY failure (unconfigured, API error, timeout) returns None so the caller degrades to the
  synchronous path. It waits inline up to a budget; TRUE async (submit → checkpoint → resume-poll via the
  chunked implement_plan) is a documented follow-up. Ref: cloud.google.com/vertex-ai/.../partner-models/claude/batch.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time

from common.llm.parse import loads_obj
from common.llm.vertex import vertex_config
from common.testplan.llm.prompts import pack_block, scenarios_prompt
from common.testplan.llm.schemas import Scenarios
from common.testplan.models import TestData, TestPlan, TestScenario
from test_plan_definition.monitoring import get_logger

log = get_logger("llm.implement.batch")

_ANTHROPIC_VERSION = "vertex-2023-10-16"  # pinned by the Vertex Claude batch schema
_DEFAULT_BUDGET_S = 3000.0


def enabled() -> bool:
    """True when the batch path is opted in (``TPD_BATCH_MODE=vertex_batch``)."""
    return os.environ.get("TPD_BATCH_MODE", "").strip().lower() == "vertex_batch"


def build_request(custom_id: str, *, system: str, user: str, max_tokens: int) -> dict:
    """One JSONL request line for the Vertex Claude batch job (system prompt-cached, thinking disabled —
    same shape as the synchronous generator, wrapped in the batch envelope)."""
    return {"custom_id": custom_id, "request": {
        "anthropic_version": _ANTHROPIC_VERSION,
        "max_tokens": max_tokens,
        "thinking": {"type": "disabled"},
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": user}],
    }}


def parse_output(text: str) -> dict[str, str]:
    """Map ``custom_id -> the model's text`` from the batch output JSONL. Each line is a result object;
    the Anthropic message may sit at the top level or nested under ``response``/``response.body``
    (Vertex wrapping varies), so we look in all three. Non-JSON / result-less lines are skipped."""
    out: dict[str, str] = {}
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        with contextlib.suppress(ValueError):
            obj = json.loads(raw)
            cid = obj.get("custom_id")
            msg = obj
            for key in ("response", "body"):  # unwrap Vertex/Anthropic nesting if present
                if isinstance(msg, dict) and isinstance(msg.get(key), dict):
                    msg = msg[key]
            content = msg.get("content") if isinstance(msg, dict) else None
            txt = "".join(b.get("text", "") for b in (content or [])
                          if isinstance(b, dict) and b.get("type") == "text")
            if cid and txt:
                out[cid] = txt
    return out


async def run_batch_scenarios(
    plan: TestPlan, plan_pack, test_data: list[TestData], *, batches: list[list[str] | None],
    now: str = "", reflections: list[str] | None = None, max_tokens: int,
) -> list[TestScenario] | None:
    """Generate all batches via ONE Vertex batch job; merge into scenarios. Returns None on total
    failure (→ caller falls back to the synchronous path); a batch whose output is missing/invalid
    degrades to the heuristic for its units alone (mirrors the sync path)."""
    cfg = vertex_config()
    if cfg is None:
        return None
    project, location, model = cfg
    summary = plan_pack.summary_text()
    system = pack_block(summary)
    reqs = [build_request(f"batch-{i}", system=system, max_tokens=max_tokens,
                          user=scenarios_prompt(plan, summary, test_data, reflections,
                                                include_context=False, focus_units=ids))
            for i, ids in enumerate(batches)]
    try:
        outputs = await asyncio.to_thread(_submit_and_collect, reqs, project=project,
                                          location=location, model=model, context_id=plan.context_id)
    except Exception as exc:  # noqa: BLE001 — preview API; degrade to the synchronous path on any error
        log.warning("vertex batch job failed (%s) — falling back to synchronous generation", exc)
        return None
    if not outputs:
        return None

    from test_plan_definition.implement.generate.scenarios import heuristic_scenarios
    merged: list[TestScenario] = []
    seen: set[str] = set()
    for i, ids in enumerate(batches):
        scs: list[TestScenario] | None = None
        text = outputs.get(f"batch-{i}")
        if text and isinstance(data := loads_obj(text), dict):
            scs = Scenarios(**data).to_scenarios(plan, now) or None
        if not scs:
            log.warning("batch %s missing/invalid in job output; heuristic fallback for its units", i)
            scs = heuristic_scenarios(plan, plan_pack, test_data, now=now,
                                      only_ids=set(ids) if ids else None)
        for s in scs:
            if s.id not in seen:
                seen.add(s.id)
                merged.append(s)
    log.info("vertex batch: %d batches → %d scenarios", len(batches), len(merged))
    return merged or None


def _submit_and_collect(reqs: list[dict], *, project: str, location: str, model: str,
                        context_id: str) -> dict[str, str]:
    """Blocking (runs in a worker thread): write the JSONL to GCS, submit a Vertex BatchPredictionJob
    against the Claude publisher model, poll to a budget, read + parse the output JSONL. PREVIEW API —
    exact create() kwargs / output layout are documented-but-unverified; raises on any failure."""
    from google.cloud import aiplatform, storage

    bucket = os.environ["GCS_BUCKET"]
    budget = _DEFAULT_BUDGET_S
    with contextlib.suppress(KeyError, ValueError, TypeError):
        budget = max(60.0, float(os.environ["TPD_BATCH_BUDGET_S"]))
    prefix = f"batches/{context_id}"
    gcs = storage.Client(project=project)
    b = gcs.bucket(bucket)
    b.blob(f"{prefix}/input.jsonl").upload_from_string("\n".join(json.dumps(r) for r in reqs))
    input_uri = f"gs://{bucket}/{prefix}/input.jsonl"
    out_prefix = f"gs://{bucket}/{prefix}/out"

    aiplatform.init(project=project, location=location)
    job = aiplatform.BatchPredictionJob.create(
        job_display_name=f"tpd-scenarios-{context_id}",
        model_name=f"publishers/anthropic/models/{model}",
        gcs_source=input_uri, gcs_destination_prefix=out_prefix,
        instances_format="jsonl", predictions_format="jsonl", sync=False)

    start = time.monotonic()
    while True:
        job.refresh()
        state = str(getattr(job, "state", ""))
        if "SUCCEEDED" in state:
            break
        if any(s in state for s in ("FAILED", "CANCELLED", "EXPIRED")):
            raise RuntimeError(f"batch job {state}")
        if time.monotonic() - start > budget:
            raise TimeoutError(f"batch job exceeded {budget:.0f}s budget")
        time.sleep(15)

    # read every *.jsonl under the output directory and parse per custom_id
    out_dir = getattr(getattr(job, "output_info", None), "gcs_output_directory", "") or out_prefix
    rel = out_dir.split(f"{bucket}/", 1)[-1].rstrip("/")
    text = "\n".join(blob.download_as_text() for blob in gcs.list_blobs(bucket, prefix=rel)
                     if blob.name.endswith(".jsonl"))
    return parse_output(text)
