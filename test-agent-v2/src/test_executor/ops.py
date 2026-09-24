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
    cov = signals.pop("ac_coverage", None) or {}      # ditto — popped BEFORE the signals line renders
    target = signals.pop("target", None) or {}
    if target:                                        # report §1 Scope — the tested item + where it ran
        lines.append("  target: " + ", ".join(f"{k}={v}" for k, v in target.items() if v))
    period = " → ".join(str(run[k]) for k in ("started_at", "finished_at") if run.get(k))
    if period:                                        # report §3 Testing Performed — the test period
        lines.append(f"  period: {period}")
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
    if cov:                                           # report §5 — the coverage matrix, GAPs and all
        lines.append(f"  AC coverage: {cov.get('covered')}/{cov.get('total')} covered, "
                     f"{cov.get('gaps')} GAP(s)")
        for r in cov.get("rows", []):
            mark = {"passed": "PASS", "failed": "FAIL", "gap": "GAP ", "unproven": "????"}.get(r["status"], "?")
            lines.append(f"    [{mark}] {r['id']}  {r['text'][:72]}")
    triage = run.get("triage") or []
    if triage:
        lines.append("  triage:")
        lines += [f"    - {t.get('verdict')}: {t.get('message')}" for t in triage]
    if run.get("status") == "done":
        # The agent does not render documents — it hands the client the data + the cue (same split as the
        # pipeline's preview reports). Offering it here is what makes the report a routine step, not an
        # afterthought someone remembers to ask for.
        lines.append(
            "\n  The run is COMPLETE. Ask the user whether to produce the TEST COMPLETION REPORT now "
            "(ISO/IEC/IEEE 29119-3 / ISTQB CTFL v4.0; a client skill renders it — e.g. "
            "`write-test-completion-report`). This run supplies:\n"
            "    - Scope (§1) ......... target: tested item + version + environment + base URL\n"
            "    - Testing performed (§3) . period: started → finished; by_engine shows the test types\n"
            "    - Test metrics (§6) ...... planned=total, executed/passed/failed, blocked=unbound, "
            "per-scenario duration_ms\n"
            "    - Open defects (§8) ...... triage verdicts (Bug); Impediments (§7) = Environment verdicts; "
            "flaky=true rows are the non-blocking failures\n"
            "    - Coverage rows .......... each result's source_refs = the requirement it covers\n"
            "  NOT derivable here — the client must supply: the story's ACCEPTANCE CRITERIA from Jira "
            "(without them an UNCOVERED AC silently vanishes from the matrix instead of showing as a GAP), "
            "the exit criteria to evaluate against (§5), deviations from plan (§4), lessons learned (§11), "
            "and the release recommendation (§12). The executor knows what RAN, not what was PROMISED.")
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
