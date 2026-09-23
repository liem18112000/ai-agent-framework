"""Run orchestration + failure triage for the Test Executor.

Slice 0 ships a STUB runner: it resolves+records the target environment and a run row on the shared
ledger, but does NOT yet drive a real browser/API run. The real Playwright + `behave` + Schemathesis
execution (design §3, phase P1) needs a sandbox + external infra and lands behind a flag in the next
slice. The triage classifier (`classify_failure`) IS real — it's the heuristic tier of the §5 JEV
cascade (JEV `Choice`/`Noul` fronts it later; today it's the deterministic fallback).
"""

from __future__ import annotations

# ponytail: heuristic triage now; the JEV DecisionProvider cascade (§5) fronts this once wired.
_BUG_HINTS = ("assertion", "assert", "expected", "wrong value", "500", "server error", "exception")
_HEAL_HINTS = ("selector", "locator", "not found", "no element", "timeout waiting", "not visible")
_ENV_HINTS = ("connection refused", "econnrefused", "dns", "unreachable", "503", "cert", "ssl", "auth")


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


def triage(failures: list[dict]) -> list[dict]:
    """Classify every failure; returns [{message, verdict}, ...]."""
    return [{"message": f.get("message", ""), "verdict": classify_failure(f)} for f in failures]


async def run_suite(store, context_id: str, env: str = "") -> dict:
    """Execute the persisted scenarios against `env` and record the run. Returns the finished run dict.

    STUB (slice 0): registers the environment + a run row with a placeholder result. Wiring the real
    runner (fetch scenarios via get_scenarios → Playwright/behave/Schemathesis in a sandbox → real
    coverage/flakiness/conformance signals) is phase P1 and replaces the body below."""
    name = env.strip() or "default"
    environment_id = await store.upsert_env(context_id, name)
    run_id = await store.start_run(context_id, environment_id)
    # ponytail: real execution deferred (P1). No scenarios are run yet — record an honest stub result.
    summary = {"passed": 0, "failed": 0, "healed": 0, "quarantined": 0, "executed": 0}
    signals = {"stub": True,
               "note": "stub runner — real Playwright/behave/Schemathesis run is phase P1 (not built)"}
    await store.finish_run(run_id, status="done", summary=summary, signals=signals, triage=[])
    return await store.get_run(run_id=run_id) or {"id": run_id, "status": "done"}
