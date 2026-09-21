"""Diagram-as-code (mermaid) generated deterministically from a persisted run.

Data-only: emits raw mermaid *source* (``flowchart …``), never HTML. The agent persists these so a
client can render them (mermaid renders natively in the Artifact viewer / Markdown) and offer each as a
downloadable ``.mmd``. No LLM, no external deps — pure functions over the plan + coverage matrix."""

from __future__ import annotations

import re


def _label(text: str, limit: int = 66) -> str:
    """A mermaid-safe quoted node label — strip characters that break mermaid, collapse ws, clip."""
    s = re.sub(r"\s+", " ", str(text or "").strip())
    s = re.sub(r'["\[\]{}()|<>#;`]', "", s)
    if len(s) > limit:
        s = s[: limit - 1].rstrip() + "…"
    return f'"{s}"'


def architecture_mmd(plan, cov: dict | None) -> str:
    """Requirements -> system-under-test (code units) -> oracle, from the coverage matrix when present,
    else a generic test-suite -> SUT -> oracle flow keyed off the plan's methodology/metrics."""
    units = (cov or {}).get("units") or []
    code = [u for u in units if u.get("category") in ("endpoint", "hub")][:8]
    reqs = [u for u in units if u.get("category") == "requirement"][:6]
    lines = ["flowchart LR", "  T([Test suite]) --> SUT"]
    if code:
        lines += ["  subgraph SUT [System under test]", "    direction TB"]
        for j, u in enumerate(code):
            tag = "endpoint" if u.get("category") == "endpoint" else "hub"
            lines.append(f'    C{j}[{_label(tag + ": " + (u.get("title") or u.get("id") or ""))}]')
        lines.append("  end")
    else:
        method = ", ".join(plan.methodology) if plan and plan.methodology else "test"
        lines += ["  subgraph SUT [System under test]", f'    C0[{_label(method + " surface")}]', "  end"]
    for j, u in enumerate(reqs):
        lines.append(f'  R{j}[{_label("req: " + (u.get("title") or u.get("id") or ""))}] -.-> SUT')
    metrics = ", ".join(plan.metrics) if plan and plan.metrics else "expected end-state"
    lines.append(f'  SUT --> O([{_label("Oracle: " + metrics)}])')
    return "\n".join(lines)


def scope_mmd(plan) -> str:
    """In-scope items with the out-of-scope items marked as excluded edges into the scope boundary."""
    in_scope = (plan.scope if plan else []) or []
    out_scope = (plan.out_of_scope if plan else []) or []
    lines = ["flowchart LR", "  subgraph IN [In scope]"]
    for j, s in enumerate(in_scope[:6]):
        lines.append(f"    S{j}[{_label(s)}]")
    if not in_scope:
        lines.append("    S0[Confirmed scope]")
    lines.append("  end")
    for j, o in enumerate(out_scope[:6]):
        lines.append(f"  O{j}[{_label(o)}] -. excluded .-> IN")
    return "\n".join(lines)


def gaps_mmd(cov: dict | None) -> str:
    """Coverage gaps as dev-to-confirm items — empty string when there are none."""
    gaps = (cov or {}).get("gaps") or []
    if not gaps:
        return ""
    lines = ["flowchart LR", "  DEV{{Dev to confirm}}"]
    for j, g in enumerate(gaps[:8]):
        label = (g.get("title") or g.get("id")) if isinstance(g, dict) else str(g)
        miss = ", ".join(g.get("missing", [])) if isinstance(g, dict) else ""
        lines.append(f'  G{j}[{_label(label + (" — missing: " + miss if miss else ""))}] --> DEV')
    return "\n".join(lines)


def build_diagrams(plan, cov: dict | None) -> dict[str, str]:
    """All diagram-as-code for a run as ``{name: mermaid_source}`` — skips any that come out empty."""
    out = {
        "architecture": architecture_mmd(plan, cov),
        "scope": scope_mmd(plan),
        "gaps": gaps_mmd(cov),
    }
    return {name: src for name, src in out.items() if src}


if __name__ == "__main__":  # tiny self-check — mermaid source is well-formed and grounded in the data
    class _P:
        methodology, metrics, scope, out_of_scope = ["api"], ["end-state"], ["import lands"], ["auth"]
    cov = {"units": [{"id": "jira:LUZ-1", "category": "requirement", "title": "ZIP import"},
                     {"id": "ep:/import", "category": "endpoint", "title": "POST /import"}],
           "gaps": [{"id": "jira:LUZ-1", "title": "ZIP import", "missing": ["negative"]}]}
    d = build_diagrams(_P(), cov)
    assert set(d) == {"architecture", "scope", "gaps"}, d
    assert d["architecture"].startswith("flowchart") and "POST /import" in d["architecture"]
    assert "excluded" in d["scope"] and "auth" in d["scope"]
    assert "Dev to confirm" in d["gaps"] and "negative" in d["gaps"]
    # no-coverage path: architecture falls back to the methodology surface, gaps drops out
    nocov = build_diagrams(_P(), {})
    assert set(nocov) == {"architecture", "scope"} and "api surface" in nocov["architecture"], nocov
    print("diagrams self-check OK:", list(d))
