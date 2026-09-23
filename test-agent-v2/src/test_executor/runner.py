"""Run orchestration + failure triage for the Test Executor.

`EXEC_RUNNER` gates execution. Default `stub`: resolve+record the environment and a placeholder run —
the whole agent+DB+gateway path is real without touching a live system. `auto`: route each scenario to
the engine that fits its nature (`runners.select_engine`, keyed on `TestScenario.methodology`) and
aggregate real pass/fail + failures. The API engine is real (httpx conformance); the Playwright/LLM
engines are stubs behind the same seam (§3, phase P1 — they drop in without dragging a browser/LLM dep
in here). The triage classifier (`classify_failure`) is the heuristic tier of the §5 JEV cascade.
"""

from __future__ import annotations

import asyncio
import os

from common.monitoring import get_logger
from test_executor.runners import ENGINES, select_engine

log = get_logger("exec.runner")

# The deterministic heuristic tier — the fallback tail of the §5 JEV cascade (see `triage`).
_BUG_HINTS = ("assertion", "assert", "expected", "wrong value", "500", "server error", "exception")
_HEAL_HINTS = ("selector", "locator", "not found", "no element", "timeout waiting", "not visible")
_ENV_HINTS = ("connection refused", "econnrefused", "dns", "unreachable", "503", "cert", "ssl", "auth")

_BUCKETS = ["Bug", "Heal", "Flaky", "Environment"]     # JEV Choice options / heuristic outputs
_TRIAGE_INSTRUCTIONS = (
    "Classify this test failure into exactly one bucket: Bug (a real product defect), Heal (a UI/"
    "selector change the test should adapt to), Flaky (non-deterministic, not a real failure), or "
    "Environment (infrastructure / connectivity / auth, not the code under test)."
)


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
        v = provider.choice(str(failure.get("message", "")), _BUCKETS, _TRIAGE_INSTRUCTIONS)
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


async def run_suite(store, context_id: str, env: str = "", *, scenarios: list[dict] | None = None,
                    base_url: str = "") -> dict:
    """Execute the scenarios against `env` and record the run. Returns the finished run dict.

    EXEC_RUNNER gates execution: `stub` (default) records an honest placeholder — the whole agent + DB
    + gateway path is real without touching a live environment; `auto` routes each scenario to the
    engine that fits its nature (`runners.select_engine`) and aggregates real pass/fail + failures."""
    name = env.strip() or "default"
    base_url = base_url or os.environ.get("EXEC_BASE_URL", "")
    environment_id = await store.upsert_env(context_id, name, base_url=base_url)
    run_id = await store.start_run(context_id, environment_id)

    if os.environ.get("EXEC_RUNNER", "stub").lower() != "auto":
        await store.finish_run(run_id, status="done",
                               summary={"passed": 0, "failed": 0, "executed": 0},
                               signals={"stub": True,
                                        "note": "stub runner — set EXEC_RUNNER=auto to route scenarios to engines"},
                               triage=[])
        return await store.get_run(run_id=run_id) or {"id": run_id, "status": "done"}

    if scenarios is None:
        scenarios = await load_scenarios(context_id)

    # ponytail: cap LLM translations per run — serial per-scenario model calls in this (still inline)
    # handler could otherwise blow the Cloud Run request ceiling (see: implement serial Vertex →
    # timeout). Raise EXEC_LLM_MAX, or move to a polled background job (P1), for larger suites.
    llm_max = int(os.environ.get("EXEC_LLM_MAX", "8"))
    passed = failed = unbound = llm_used = 0
    failures: list[dict] = []
    by_engine: dict[str, int] = {}
    for sc in scenarios:
        name = select_engine(sc)
        by_engine[name] = by_engine.get(name, 0) + 1
        if _needs_llm(name, sc):
            if llm_used >= llm_max:
                unbound += 1
                continue                 # over the per-run LLM budget — record unbound, make no call
            llm_used += 1
        res = await ENGINES[name].run(sc, base_url=base_url)
        if not res.ran:
            unbound += 1
            continue
        if res.passed:
            passed += 1
        else:
            failed += 1
            failures += [{"message": o.message, "flaky": o.flaky,
                          "scenario": sc.get("title") or sc.get("id")} for o in res.outcomes if not o.ok]

    summary = {"passed": passed, "failed": failed, "unbound": unbound,
               "executed": passed + failed, "by_engine": by_engine}
    verdicts = await asyncio.to_thread(triage, failures)   # JEV cascade is sync/blocking — run off-loop
    await store.finish_run(run_id, status="done", summary=summary,
                           signals={"failures": failures}, triage=verdicts)
    return await store.get_run(run_id=run_id) or {"id": run_id, "status": "done"}
