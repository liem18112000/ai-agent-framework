"""Framework-neutral rendering for the Test Executor — pure functions, no ADK, no I/O."""

from __future__ import annotations


def render_run(run: dict | None) -> str:
    """One run row → readable lines (status, env, summary counts, signals, triage verdicts)."""
    if not run:
        return "No run found for this context."
    lines = [f"Run {run.get('id')} — status: {run.get('status')}",
             f"  environment: {run.get('environment_id') or '(none)'}"]
    summary = run.get("summary") or {}
    if summary:
        lines.append("  summary: " + ", ".join(f"{k}={v}" for k, v in summary.items()))
    signals = run.get("signals") or {}
    if signals:
        lines.append("  signals: " + ", ".join(f"{k}={v}" for k, v in signals.items()))
    triage = run.get("triage") or []
    if triage:
        lines.append("  triage:")
        lines += [f"    - {t.get('verdict')}: {t.get('message')}" for t in triage]
    return "\n".join(lines)


def render_envs(envs: list[dict]) -> str:
    """The environments seen for a context → one line each."""
    if not envs:
        return "No environments recorded for this context yet."
    out = [f"{len(envs)} environment(s):"]
    for e in envs:
        base = e.get("base_url") or "(no base_url)"
        out.append(f"  - {e.get('name')} [{base}] last_seen={e.get('last_seen')}")
    return "\n".join(out)
