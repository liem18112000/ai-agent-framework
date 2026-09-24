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
    signals = dict(run.get("signals") or {})
    results = signals.pop("results", None) or []      # rendered as rows below, not as a k=v blob
    if signals:
        lines.append("  signals: " + ", ".join(f"{k}={v}" for k, v in signals.items()))
    if results:
        lines.append(f"  results ({len(results)} scenarios — the report's coverage rows):")
        for r in results:
            where = " ".join(x for x in (r.get("method"), r.get("path")) if x)
            refs = ",".join(r.get("source_refs") or [])
            head = f"    - [{r.get('status')}] {r.get('title')}"
            meta = " | ".join(x for x in (f"engine={r.get('engine')}", where, f"covers={refs}" if refs else "",
                                          f"{r.get('duration_ms')}ms") if x)
            lines.append(f"{head}  ({meta})")
            lines += [f"        ! {m}" for m in (r.get("messages") or [])]
    triage = run.get("triage") or []
    if triage:
        lines.append("  triage:")
        lines += [f"    - {t.get('verdict')}: {t.get('message')}" for t in triage]
    if run.get("status") == "done":
        # The agent does not render documents — it hands the client the data + the cue (same split as the
        # pipeline's preview reports). Offering it here is what makes the report a routine step, not an
        # afterthought someone remembers to ask for.
        lines.append("\n  The run is COMPLETE. Ask the user whether to produce the test completion report "
                     "now (a client rendering skill builds it — e.g. `write-test-completion-report`). "
                     "Everything it needs is above plus `get_run_report`: per-scenario results with their "
                     "covered requirement ids, triage verdicts, the environment, and the counts. The report "
                     "still needs the story's acceptance criteria from Jira for the coverage matrix.")
    return "\n".join(lines)


def render_heal(result: dict) -> str:
    """A heal_step proposal → readable lines. The patch is a proposal for a human Yes/No, not applied."""
    status = "HEALED — patch verified (re-run passed)" if result.get("healed") else "NOT healed"
    lines = [f"Heal: {status}", f"  {result.get('note', '')}"]
    if result.get("patch"):
        lines.append(f"  proposed patch ({result.get('engine')}): {result['patch']}")
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
