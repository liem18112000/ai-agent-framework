"""laya System-1 decision sidecar — wraps the in-process `laya` library behind ONE HTTP endpoint.

laya (JEV's open-source twin) is a heavy torch/transformers library that downloads multi-GB checkpoints;
running it as a lone sidecar keeps that weight out of the agent images. The `LayaProvider`
(common/adk/providers/laya.py) is this service's client. Contract:

  POST /decide  {"state": <str|obj>, "questions": {"<q>": {"type","instructions","criteria"?}}}
             -> {"answers": {"<q>": {"choice"|"score"|"noul", "confidence", "probabilities"?}}}

Env: LAYA_MODEL (default "convaiinnovations/laya"), PORT (9000), HF_HOME (checkpoint cache dir).
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()
_agent = None


def _get():
    """Lazy-load the laya checkpoint once (first request pays the download/warm-up)."""
    global _agent
    if _agent is None:
        import laya

        _agent = laya.load(os.environ.get("LAYA_MODEL", "convaiinnovations/laya"))
    return _agent


class DecideRequest(BaseModel):
    state: object
    questions: dict


@app.get("/livez")
def livez():
    return {"status": "ok"}


@app.post("/decide")
def decide(req: DecideRequest):
    state = req.state if isinstance(req.state, dict) else {"text": str(req.state)}
    result = _get().predict(state, req.questions)
    answers = result["answers"] if isinstance(result, dict) else getattr(result, "answers", result)
    return {"answers": answers}
