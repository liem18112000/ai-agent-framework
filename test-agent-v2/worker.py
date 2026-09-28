"""Cloud Run push-subscription endpoint (Phase C) — the scenario-generation worker.

A Pub/Sub PUSH subscription POSTs each batch job here; the handler runs it in its OWN process (direct
`complete()`, no ADK Runner → sidesteps the in-process limits), writes the result to GCS, and returns
204 to ack. A non-2xx nacks → Pub/Sub retries, then dead-letters. Served like any agent: `uvicorn worker:app`.

Env: VERTEX_PROJECT/LOCATION/MODEL (for `complete`), GCS_BUCKET. Idempotent: the result blob is keyed by
(ctx, run, batch), so a redelivery just overwrites.
"""

from __future__ import annotations

import asyncio
import base64

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Route

from common.monitoring import get_logger
from test_plan_definition.implement.generate.workers import handle_job

log = get_logger("worker")


async def _push(request: Request) -> Response:
    """Handle one Pub/Sub push message: {message: {data: base64(job-json)}}."""
    try:
        envelope = await request.json()
        data = base64.b64decode((envelope.get("message") or {}).get("data") or b"")
    except Exception as exc:  # noqa: BLE001 — malformed push: ack (204) so it isn't retried forever
        log.warning("worker: bad push envelope (%s) — dropping", exc)
        return Response(status_code=204)
    try:
        await asyncio.to_thread(handle_job, data)  # handle_job is blocking (complete + GCS write)
    except Exception as exc:  # noqa: BLE001 — 500 nacks → Pub/Sub retries, then dead-letters
        log.warning("worker: job failed (%s) — nack", exc)
        return PlainTextResponse(str(exc), status_code=500)
    return Response(status_code=204)  # ack


app = Starlette(routes=[
    Route("/", _push, methods=["POST"]),
    Route("/livez", lambda _r: PlainTextResponse("ok")),
])
