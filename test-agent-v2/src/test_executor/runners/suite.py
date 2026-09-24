"""Run orchestration + failure triage for the Test Executor.

`EXEC_RUNNER` gates execution. Default `stub`: resolve+record the environment and a placeholder run —
the whole agent+DB+gateway path is real without touching a live system. `auto`: route each scenario to
the engine that fits its nature (`runners.select_engine`, keyed on `TestScenario.methodology`) and
aggregate real pass/fail + failures — chunked + polled so no call blocks past the request timeout. All
three engines are real (API httpx-conformance · LLM NL→request · browser Playwright). The triage
classifier (`classify_failure`) is the heuristic tier of the §5 JEV cascade.
"""

from __future__ import annotations

import asyncio
import os

from common.monitoring import get_logger
from test_executor.runners.select import ENGINES, select_engine

log = get_logger("exec.runner")

# The deterministic heuristic tier — the fallback tail of the §5 JEV cascade (see `triage`).
_BUG_HINTS = ("assertion", "assert", "expected", "wrong value", "500", "server error", "exception")
_HEAL_HINTS = ("selector", "locator", "not found", "no element", "timeout waiting", "not visible")
_ENV_HINTS = ("connection refused", "econnrefused", "dns", "unreachable", "503", "cert", "ssl", "auth")

_BUCKETS = ["Bug", "Heal", "Flaky", "Environment"]     # JEV Choice options / heuristic outputs
# The classifier instruction now lives in the store-backed registry (`exec.triage`, test_executor.prompts)
# so it is DB-publishable/versioned like tpd.report/kga.report; the compiled default is the offline fallback.


def classify_failure(failure: dict) -> str:
    """Map one failure to a triage bucket: Bug | Heal | Flaky | Environment.

    `failure` = {message, flaky?}. A confirmed-oscillating step is Flaky; otherwise the message text
    routes it. Defaults to Bug (fail loud — a real regression must not be silently healed/quarantined)."""
    if failure.get("flaky"):
        return "Flaky"
    msg = str(failure.get("message", "")).lower()
    if any(h in msg for h in _ENV_HINTS):
        return "Environment"
    if any(h in msg for h in _HEAL_HINTS):
        return "Heal"
    if any(h in msg for h in _BUG_HINTS):
        return "Bug"
    return "Bug"


def _jev_bucket(failure: dict, provider, conf_min: float) -> str | None:
    """JEV Choice over the four buckets — returns the chosen bucket only when confident, else None so
    the caller falls back to the heuristic. Any decision error → None (never breaks triage)."""
    try:
        from test_executor.prompts import triage_instructions
        v = provider.choice(str(failure.get("message", "")), _BUCKETS, triage_instructions())
    except Exception as exc:  # noqa: BLE001 — a decision-backend failure must never break triage
        log.warning("triage: JEV choice failed (%s) → heuristic", exc)
        return None
    if v is not None and v.confidence >= conf_min and v.value in _BUCKETS:
        return str(v.value)
    return None


def triage(failures: list[dict]) -> list[dict]:
    """Classify each failure Bug/Heal/Flaky/Environment (§5 cascade). A configured, confident JEV
    `DecisionProvider` (TPD_DECISION_BACKEND) FRONTS the deterministic heuristic; otherwise, or on the
    low-confidence tail / any error, the heuristic decides — strictly additive, default OFF. SYNC
    (JEV is blocking) — call via asyncio.to_thread from an event loop."""
    from common.adk.providers import get_decision_provider
    provider = get_decision_provider()
    use_jev = provider is not None and provider.is_configured()
    try:
        conf_min = float(os.environ.get("EXEC_TRIAGE_CONF_MIN", "0.6"))
    except ValueError:
        conf_min = 0.6
    out = []
    for f in failures:
        verdict = None
        if use_jev and not f.get("flaky"):    # a proven-flaky is a deterministic signal — don't re-judge
            verdict = _jev_bucket(f, provider, conf_min)
        out.append({"message": f.get("message", ""), "verdict": verdict or classify_failure(f)})
    return out


def _needs_llm(engine: str, sc: dict) -> bool:
    """True if routing `sc` to `engine` will make an LLM translation call — so it counts against the
    per-run budget. Pre-bound scenarios (llm with a `request`, browser with a `browser` plan) don't."""
    if engine == "llm":
        req = sc.get("request")
        return not (isinstance(req, dict) and req.get("path"))
    if engine == "browser":
        return not isinstance(sc.get("browser"), dict)
    return False


async def load_scenarios(context_id: str) -> list[dict]:
    """Read the persisted scenarios for `context_id` from the shared memory bank — the same
    `scenarios.json` TPD writes via `common.testplan.memory.write_scenarios`. Returns dicts (carrying
    the `methodology` routing key); [] when none / no bank. Blocking bank I/O runs off the event loop."""
    from dataclasses import asdict

    def _read() -> list[dict]:
        from common.memory.factory import build_bank
        from common.testplan import memory as tp_store
        return [asdict(s) for s in tp_store.read_scenarios(build_bank(), context_id)]

    try:
        return await asyncio.to_thread(_read)
    except Exception as exc:  # noqa: BLE001 — a missing/empty bank degrades to [], never crashes the run
        log.warning("load_scenarios(%s) failed: %s", context_id, exc)
        return []


_CHUNK_DEFAULT = 5


def _chunk_size() -> int:
    try:
        return max(1, int(os.environ.get("EXEC_CHUNK", str(_CHUNK_DEFAULT))))
    except ValueError:
        return _CHUNK_DEFAULT


async def _resolve_upload_refs(scenarios: list[dict], context_id: str) -> None:
    """Inject bank fixture bytes into bound file-upload scenarios: for each scenario whose
    `request.upload` names a `data_ref`, load that TestData from the bank and set `upload.content` from
    its base64 payload (TestData.spec = {filename, content_type, b64}). This is what lets a file-upload
    test live in the bank — the model can't carry raw bytes, so it references a fixture by id. No-op when
    nothing references a fixture. Blocking bank I/O runs off the event loop. A missing fixture leaves the
    upload unresolved → the engine reports a real failure rather than crashing the run."""
    need = [s for s in scenarios
            if isinstance(s.get("request"), dict)
            and isinstance(s["request"].get("upload"), dict)
            and s["request"]["upload"].get("data_ref") and s["request"]["upload"].get("content") is None]
    if not need:
        return
    import base64
    from asyncio import to_thread

    def _load() -> dict:
        from common.memory.factory import build_bank
        from common.testplan.memory.writers import read_test_data
        return {d.id: d for d in read_test_data(build_bank(), context_id)}

    try:
        by_id = await to_thread(_load)
    except Exception as exc:  # noqa: BLE001 — a missing/broken bank leaves uploads unresolved, never crashes
        log.warning("exec: could not load test-data for uploads: %s", type(exc).__name__)
        return
    for s in need:
        up = s["request"]["upload"]
        spec = getattr(by_id.get(up["data_ref"]), "spec", {}) or {}
        if not spec.get("b64"):
            continue
        try:
            up["content"] = base64.b64decode(spec["b64"])
        except (ValueError, TypeError):  # a malformed fixture degrades THIS upload, not the whole run
            log.warning("exec: bad base64 in upload fixture %s — leaving unresolved", up.get("data_ref"))
            continue
        up.setdefault("filename", spec.get("filename"))
        up.setdefault("content_type", spec.get("content_type"))


async def run_suite(store, context_id: str, env: str = "", *, scenarios: list[dict] | None = None,
                    base_url: str = "") -> dict:
    """Advance the execution run for a context by ONE chunk; return the run dict (status 'in_progress'
    while chunks remain, else 'done'). The run is POLLED — the client re-invokes until done (like
    implement_plan) so no single call blocks past the Cloud Run request timeout.

    EXEC_RUNNER gates execution. `stub` (default): a one-shot honest placeholder (no live system).
    `auto`: route each scenario to the engine that fits its nature and aggregate real pass/fail —
    EXEC_CHUNK scenarios at a time, checkpointed to the ledger so a resume CONTINUES, not restarts.

    Multi-env (§4): `env` NAMES a target in EXEC_ENVIRONMENTS ({base_url, auth}); its base_url + auth are
    resolved from there, falling back to the `base_url` arg / EXEC_BASE_URL. The ledger records base_url +
    the auth KIND (creds_ref), never the secret."""
    from test_executor.environments import resolve_env
    env_cfg = resolve_env(env)
    base_url = base_url or env_cfg.get("base_url") or os.environ.get("EXEC_BASE_URL", "")
    if base_url and "@" in base_url:  # strip any inline userinfo/creds so they never hit the ledger/reply
        import httpx
        base_url = str(httpx.URL(base_url).copy_with(username=None, password=None))
    auth_cfg = env_cfg.get("auth") or {}
    creds_ref = str(auth_cfg.get("type", "")) or None      # the auth KIND for the ledger (never the secret)

    if os.environ.get("EXEC_RUNNER", "stub").lower() != "auto":
        environment_id = await store.upsert_env(context_id, env.strip() or "default", base_url=base_url,
                                                 creds_ref=creds_ref)
        run_id = await store.start_run(context_id, environment_id)
        await store.finish_run(run_id, status="done",
                               summary={"passed": 0, "failed": 0, "executed": 0},
                               signals={"stub": True,
                                        "note": "stub runner — set EXEC_RUNNER=auto to route scenarios to engines"},
                               triage=[])
        return await store.get_run(run_id=run_id) or {"id": run_id, "status": "done"}

    if scenarios is None:
        scenarios = await load_scenarios(context_id)
    await _resolve_upload_refs(scenarios, context_id)   # inject bank fixture bytes into bound file uploads
    total = len(scenarios)

    latest = await store.get_run(context_id=context_id)
    if latest and latest.get("status") == "in_progress":       # resume the running chunked run
        run_id = latest["id"]
        s, prog = latest.get("summary") or {}, latest.get("signals") or {}
        passed, failed, unbound = int(s.get("passed", 0)), int(s.get("failed", 0)), int(s.get("unbound", 0))
        by_engine = dict(s.get("by_engine") or {})
        cursor, llm_used = int(prog.get("cursor", 0)), int(prog.get("llm_used", 0))
        failures = list(prog.get("failures") or [])
    else:                                                       # start a fresh run
        environment_id = await store.upsert_env(context_id, env.strip() or "default", base_url=base_url,
                                                 creds_ref=creds_ref)
        run_id = await store.start_run(context_id, environment_id)
        passed = failed = unbound = cursor = llm_used = 0
        by_engine, failures = {}, []

    # Prepare auth once per chunk (§4 prepare phase). ponytail: a bearer_fetch re-fetches each poll —
    # fine at chunk cadence; cache on the run if token cost matters.
    from test_executor.auth import authenticate
    auth = await authenticate(auth_cfg, base_url=base_url)

    # Pillar 3: ground API execution on the target's OpenAPI spec (env `spec_url`, e.g. /v3/api-docs),
    # fetched once per chunk with the run's auth. None → engines fall back to ungrounded LLM guesses.
    spec_ctx = None
    if env_cfg.get("spec_url"):
        from test_executor.openapi import fetch_spec, parse_operations
        raw_spec = await fetch_spec(env_cfg["spec_url"], base_url=base_url, headers=getattr(auth, "headers", None))
        if raw_spec:
            spec_ctx = {"spec": raw_spec, "ops": parse_operations(raw_spec)}

    llm_max = int(os.environ.get("EXEC_LLM_MAX", "8"))
    for sc in scenarios[cursor:cursor + _chunk_size()]:
        name = select_engine(sc)
        by_engine[name] = by_engine.get(name, 0) + 1
        cursor += 1
        if _needs_llm(name, sc):
            if llm_used >= llm_max:
                unbound += 1
                continue                 # over the per-run LLM budget — record unbound, make no call
            llm_used += 1
        try:
            res = await ENGINES[name].run(sc, base_url=base_url, auth=auth, spec=spec_ctx,
                                          path_vars=env_cfg.get("path_vars") or {})
        except Exception as exc:  # noqa: BLE001 — one scenario's crash must not wedge the whole chunked run
            log.warning("exec: scenario %r crashed engine %s: %s", sc.get("title") or sc.get("id"), name, exc)
            failed += 1
            failures.append({"message": f"engine {name} crashed: {type(exc).__name__}", "flaky": False,
                             "scenario": sc.get("title") or sc.get("id")})
            continue                  # cursor already advanced above → the run progresses, never re-wedges
        if not res.ran:
            unbound += 1
        elif res.passed:
            passed += 1
        else:
            failed += 1
            failures += [{"message": o.message, "flaky": o.flaky,
                          "scenario": sc.get("title") or sc.get("id")} for o in res.outcomes if not o.ok]

    summary = {"passed": passed, "failed": failed, "unbound": unbound,
               "executed": passed + failed, "by_engine": by_engine}
    if cursor < total:                                         # more chunks remain → checkpoint + poll
        await store.save_progress(run_id, summary=summary,
                                  signals={"cursor": cursor, "total": total, "failures": failures,
                                           "llm_used": llm_used})
        return await store.get_run(run_id=run_id) or {"id": run_id, "status": "in_progress"}

    verdicts = await asyncio.to_thread(triage, failures)       # JEV cascade is sync/blocking — off-loop
    await store.finish_run(run_id, status="done", summary=summary,
                           signals={"failures": failures, "total": total}, triage=verdicts)
    return await store.get_run(run_id=run_id) or {"id": run_id, "status": "done"}


async def heal_step(store, context_id: str, step_id: str, *, base_url: str = "",
                    scenarios: list[dict] | None = None) -> dict:
    """Propose + verify a fix for ONE failed step of the latest run (§3.1 self-heal). Finds the failure
    by `step_id` (its scenario title/id), re-translates the scenario with the failure fed back, and
    re-runs to check the patch works. Returns {healed, engine, patch, note} — the patch is a PROPOSAL,
    surfaced for a human Yes/No; it is NEVER applied here (no silent retarget)."""
    from test_executor.runners.translate import heal

    base_url = base_url or os.environ.get("EXEC_BASE_URL", "")
    run = await store.get_run(context_id=context_id)
    failures = ((run or {}).get("signals") or {}).get("failures") or []
    fail = next((f for f in failures if str(f.get("scenario")) == step_id), None)
    if fail is None:
        return {"healed": False, "note": f"no failed step '{step_id}' in the latest run to heal"}
    from common.adk.model import model_configured
    if not (base_url and model_configured()):
        return {"healed": False, "note": "healing needs a model provider + base_url (EXEC_BASE_URL)"}
    if scenarios is None:
        scenarios = await load_scenarios(context_id)
    sc = next((s for s in scenarios if step_id in (s.get("title"), s.get("id"))), None)
    if sc is None:
        return {"healed": False, "note": f"scenario '{step_id}' not found in the bank to heal"}
    plan, res = await heal(sc, fail.get("message", ""), base_url=base_url)
    return {"healed": bool(res.ran and res.passed), "engine": res.engine, "patch": plan,
            "note": "PROPOSED patch — surfaced for human Yes/No; not applied automatically (no silent retarget)."}
