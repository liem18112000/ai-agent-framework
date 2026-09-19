"""Deterministic QA/QC test-plan report, rendered from the persisted run in the memory bank.

One self-contained, printable page with a sticky section nav and the 10 canonical QA/QC sections:
  1. Summary & test environment   2. Architecture (mermaid)   3. Confirmed scope decisions
  4. Methodology & test-design    5. Test scenarios (BDD + downloadable fixtures + detailed steps)
  6. Coverage matrix              7. Spec gaps & dev-confirmation (explained + diagram)
  8. Out of scope (explained + diagram)   9. Benchmarks (PQS/TPS, component-by-component)
  10. Deliverables & next steps

Pure render — reads via `common.testplan.memory` (+ optional benchmark blob) only; no writes, no
`test_plan_definition` import. Generic render helpers (escaping, markdown, mermaid, downloads, links,
the stylesheet and the page shell) are shared with the knowledge report in `common.report.util`."""

from __future__ import annotations

import json

from common.report.util import PQS_META as _PQS_META
from common.report.util import TPS_META as _TPS_META
from common.report.util import (
    all_jira_keys as _all_jira_keys,
)
from common.report.util import (
    download as _download,
)
from common.report.util import (
    e as _e,
)
from common.report.util import (
    fmt as _fmt,
)
from common.report.util import (
    grade as _grade,
)
from common.report.util import (
    jira_link as _jira_link,
)
from common.report.util import (
    md as _md,
)
from common.report.util import (
    mermaid as _mermaid,
)
from common.report.util import (
    mlabel as _mlabel,
)
from common.report.util import (
    nav_and_sections as _nav_and_sections,
)
from common.report.util import (
    page as _page,
)
from common.report.util import (
    resource as _resource,
)
from common.testplan import memory as store
from common.testplan.models import effective_kinds

# kind -> css chip class (unknown kinds fall back to "other")
_KIND_CLASS = {
    "happy": "happy", "negative": "negative", "boundary": "boundary", "error": "error",
    "security": "security", "concurrency": "concurrency", "i18n": "encoding", "encoding": "encoding",
    "performance": "perf", "compliance": "other", "accessibility": "other", "migration": "other",
    "resilience": "other",
}
_KIND_ORDER = {k: i for i, k in enumerate(
    ["happy", "negative", "boundary", "error", "security", "concurrency", "i18n", "encoding",
     "performance", "compliance", "accessibility", "migration", "resilience"])}


_SECTIONS = [
    ("s-summary", "Summary & test environment"),
    ("s-arch", "Architecture"),
    ("s-decisions", "Confirmed scope decisions"),
    ("s-method", "Methodology & test-design"),
    ("s-scenarios", "Test scenarios"),
    ("s-coverage", "Coverage matrix"),
    ("s-gaps", "Spec gaps & dev-confirmation"),
    ("s-oos", "Out of scope"),
    ("s-bench", "Benchmarks"),
    ("s-deliver", "Deliverables & next steps"),
]


# ---- domain primitives (generic ones live in common.report.util) -----------------------------------
def _chip(kind: str) -> str:
    return f'<span class="chip {_KIND_CLASS.get(kind, "other")}">{_e(kind)}</span>'


def _steps_by_scenario(steps) -> dict:
    by: dict = {}
    for st in steps:
        by.setdefault(st.scenario_id, []).append(st)
    for v in by.values():
        v.sort(key=lambda s: s.order)
    return by


def _ordered(scenarios):
    return sorted(scenarios, key=lambda s: (_KIND_ORDER.get(s.kind, 99), s.title))


def _arch_mermaid(cov: dict, plan) -> str:
    """Architecture diagram: requirements -> system-under-test (code units) -> oracle, from the coverage
    matrix when present, else a generic test-suite → SUT → oracle flow."""
    units = cov.get("units") or []
    code = [u for u in units if u.get("category") in ("endpoint", "hub")][:8]
    reqs = [u for u in units if u.get("category") == "requirement"][:6]
    lines = ["flowchart LR", "  T([Test suite]) --> SUT"]
    if code:
        lines.append("  subgraph SUT [System under test]")
        lines.append("    direction TB")
        for j, u in enumerate(code):
            tag = "endpoint" if u.get("category") == "endpoint" else "hub"
            lines.append(f'    C{j}[{_mlabel(tag + ": " + (u.get("title") or u.get("id") or ""))}]')
        lines.append("  end")
    else:
        method = ", ".join(plan.methodology) if plan and plan.methodology else "test"
        lines.append(f'  subgraph SUT [System under test]\n    C0[{_mlabel(method + " surface")}]\n  end')
    for j, u in enumerate(reqs):
        lines.append(f'  R{j}[{_mlabel("req: " + (u.get("title") or u.get("id") or ""))}] -.-> SUT')
    metrics = ", ".join(plan.metrics) if plan and plan.metrics else "expected end-state"
    lines.append(f'  SUT --> O([{_mlabel("Oracle: " + metrics)}])')
    return _mermaid("\n".join(lines))


def _gap_mermaid(items: list[str]) -> str:
    lines = ["flowchart LR", "  DEV{{Dev to confirm}}"]
    for j, g in enumerate(items[:6]):
        lines.append(f'  G{j}[{_mlabel(g)}] --> DEV')
    return _mermaid("\n".join(lines))


def _oos_mermaid(in_scope: list[str], out_scope: list[str]) -> str:
    lines = ["flowchart LR", "  subgraph IN [In scope]"]
    for j, s in enumerate(in_scope[:5]):
        lines.append(f'    S{j}[{_mlabel(s)}]')
    if not in_scope:
        lines.append("    S0[Confirmed scope]")
    lines.append("  end")
    for j, o in enumerate(out_scope[:6]):
        lines.append(f'  O{j}[{_mlabel(o)}] -. excluded .-> IN')
    return _mermaid("\n".join(lines))


# ---- sections --------------------------------------------------------------------------------------
def _sec_summary(plan, brief, scenarios, keys, test_data) -> str:
    method = ", ".join(plan.methodology) if plan and plan.methodology else "&mdash;"
    kinds = ", ".join(effective_kinds(plan)) if plan else "happy, negative, boundary, error"
    conf = plan.confidence if plan else "&mdash;"
    scope = "".join(f"<li>{_e(x)}</li>" for x in (plan.scope if plan else []))
    # test environment: ticket links + every source ref as a clickable/downloadable resource
    tickets = " ".join(_jira_link(k) for k in keys) or "&mdash;"
    refs = (plan.source_refs if plan else []) or []
    resources = " ".join(f'<span class="res">{_resource(r)}</span>' for r in refs) or \
        '<span class="muted">none recorded</span>'
    summary_html = _md(brief) if brief else (
        f"<ul class='scopelist scope-in'>{scope}</ul>" if scope else "<p class='muted'>&mdash;</p>")
    return (
        '<p class="lead">What the system does, what this ticket changes, and where it is tested.</p>'
        f'<div class="box">{summary_html}</div>'
        '<div class="kv">'
        f'<div><span class="k">Ticket(s)</span><span class="v">{tickets}</span></div>'
        f'<div><span class="k">Test service / methodology</span><span class="v">{_e(method)}</span></div>'
        f'<div><span class="k">Test kinds</span><span class="v">{_e(kinds)}</span></div>'
        f'<div><span class="k">Scenarios</span><span class="v">{len(scenarios)}</span></div>'
        f'<div><span class="k">Test-data fixtures</span><span class="v">{len(test_data)}</span></div>'
        f'<div><span class="k">Plan confidence</span><span class="v">{_e(conf)}</span></div>'
        '</div>'
        '<h3>Test environment &amp; resources</h3>'
        '<p class="lead">Every ticket, attachment and source the plan is built on — click to open, or '
        'download the fixtures in §5.</p>'
        f'<div class="reslist">{resources}</div>')


def _sec_arch(cov, plan) -> str:
    return ('<p class="lead">System under test, the requirements that drive it, and the oracle each '
            'scenario checks against. Derived from the coverage matrix.</p>'
            + _arch_mermaid(cov, plan))


def _sec_decisions(decisions) -> str:
    if not decisions:
        return "<p class='muted'>No scope decisions were recorded for this run.</p>"
    from collections import defaultdict
    by_round: dict = defaultdict(list)
    for d in decisions:
        by_round[d.round or "other"].append(d)
    out = [('<p class="lead">Every scope call confirmed during the define stage, with its rationale, the '
            'options rejected, and its provenance.</p>')]
    for rnd in ("methodology", "scope", "metrics", "test-design", "other"):
        ds = by_round.get(rnd)
        if not ds:
            continue
        out.append(f"<h3>{_e(rnd)}</h3>")
        for d in ds:
            rejected = (f'<div class="d-rej"><b>Rejected:</b> {_e("; ".join(d.rejected))}</div>'
                        if d.rejected else "")
            chosen = f'<div class="d-chosen">{_e(d.chosen)}</div>' if d.chosen else ""
            why = f'<div class="d-why"><b>Why:</b> {_e(d.rationale)}</div>' if d.rationale else ""
            prov = (" · ".join(_resource(r) for r in d.source_refs)) if d.source_refs else ""
            prov_html = f'<div class="d-prov">{prov}</div>' if prov else ""
            out.append(
                f'<div class="dcard"><div class="d-head"><span class="pill {_e(d.confidence)}">'
                f'{_e(d.confidence)}</span><span class="d-stmt">{_e(d.statement)}</span></div>'
                f'{chosen}{why}{rejected}{prov_html}</div>')
    return "\n".join(out)


def _sec_method(plan) -> str:
    if not plan:
        return "<p class='muted'>No plan recorded.</p>"
    def _ul(items):
        return ("<ul class='tight'>" + "".join(f"<li>{_e(x)}</li>" for x in items) + "</ul>") \
            if items else "<p class='muted'>&mdash;</p>"
    return (
        '<p class="lead">How the system is exercised and how each test derives its cases.</p>'
        '<div class="grid2">'
        f'<div class="box"><h3>Methodology</h3>{_ul(plan.methodology)}</div>'
        f'<div class="box"><h3>Test-design techniques</h3>{_ul(plan.test_design)}</div>'
        f'<div class="box"><h3>Metrics — what "passed" means</h3>{_ul(plan.metrics)}</div>'
        f'<div class="box"><h3>Test kinds in scope</h3>{_ul(effective_kinds(plan))}</div>'
        '</div>')


def _gherkin_one(sc, sts) -> str:
    lines = [f"@{sc.kind} @{sc.methodology}", f"Scenario: {sc.title}"]
    if sts:
        for st in sts:
            lines.append(f"  {st.keyword or 'When'} {st.action}")
            if st.expected and not st.keyword:
                lines.append(f"  Then {st.expected}")
    else:
        for p in sc.preconditions:
            lines.append(f"  Given {p}")
        if sc.description:
            lines.append(f"  When {sc.description}")
    return "\n".join(lines)


def _sec_scenarios(scenarios, steps_by, td_by_id) -> str:
    if not scenarios:
        return "<p class='muted'>No scenarios generated for this run.</p>"
    out = [('<p class="lead">Each case in BDD form, with detailed steps, its oracle, and its test-data '
            'fixtures ready to download.</p>')]
    for i, sc in enumerate(_ordered(scenarios), 1):
        sts = steps_by.get(sc.id, [])
        # detailed step flow
        flow = []
        for st in sts:
            kw = _e(st.keyword or "step")
            exp = f'<div class="fl-exp">&rarr; expect: {_e(st.expected)}</div>' if st.expected else ""
            data = ""
            if st.data_refs:
                data = ('<div class="fl-data">data: '
                        + ", ".join(f'<code>{_e(r.split(":")[-1])}</code>' for r in st.data_refs) + "</div>")
            flow.append(f'<div class="fl-step"><span class="fl-kw">{kw}</span>'
                        f'<div class="fl-body"><div class="fl-act">{_e(st.action)}</div>{exp}{data}</div></div>')
        if not flow:
            for p in sc.preconditions:
                flow.append(f'<div class="fl-step"><span class="fl-kw">given</span>'
                            f'<div class="fl-body"><div class="fl-act">{_e(p)}</div></div></div>')
            if sc.description:
                flow.append(f'<div class="fl-step"><span class="fl-kw">verify</span>'
                            f'<div class="fl-body"><div class="fl-act">{_e(sc.description)}</div></div></div>')
        # oracle = last then/expected
        then = [s for s in sts if s.keyword.lower() in ("then", "and")] or sts
        oracle = (then[-1].expected or then[-1].action) if then else ""
        # per-scenario downloadable fixtures (resolved from data_refs)
        fixtures = {r.split(":")[-1]: (td_by_id[r].spec if r in td_by_id else {})
                    for r in sc.data_refs}
        short = sc.id.split(":")[-1] or f"case{i}"
        dl_data = (_download("test data", f"{short}-fixtures.json",
                             json.dumps(fixtures, ensure_ascii=False, indent=2)) if fixtures else "")
        dl_feat = _download("feature", f"{short}.feature", _gherkin_one(sc, sts), mime="text/plain")
        why = " ".join(x for x in (sc.description, sc.rationale) if x) or "Exercises the behaviour under test."
        out.append(
            f'<div class="wf"><div class="wf-head"><span class="wf-n">{i}</span>{_chip(sc.kind)}'
            f'<span class="wf-title">{_e(sc.title)}</span></div>'
            f'<p class="wf-why">{_e(why)}</p>'
            f'<div class="fl">{"".join(flow) or "<span class=muted>No steps.</span>"}</div>'
            + (f'<div class="oracle"><span class="tag">oracle</span>{_e(oracle)}</div>' if oracle else "")
            + f'<div class="dlrow">{dl_feat}{dl_data}</div></div>')
    return "\n".join(out)


def _sec_coverage(cov, cov_md) -> str:
    parts = []
    if cov:
        parts.append('<div class="bmrow">'
                     f'<div class="score"><div class="n">{cov.get("requirement_cells_covered", 0)}/'
                     f'{cov.get("requirement_cells", 0)}</div><div class="l">requirement cells covered</div></div>'
                     f'<div class="score"><div class="n">{cov.get("code_units_reached", 0)}/'
                     f'{cov.get("code_units", 0)}</div><div class="l">code units reached</div></div></div>')
    if cov_md:
        parts.append(_md(cov_md))
    elif cov and cov.get("units"):
        # render the requirement × kind matrix from the dict
        kinds = cov.get("kinds") or []
        covered = cov.get("covered") or {}
        reqs = [u for u in cov["units"] if u.get("category") == "requirement"]
        th = "".join(f"<th>{_e(k)}</th>" for k in kinds)
        rows = []
        for u in reqs:
            cells = "".join(
                f'<td class="cov {"y" if k in covered.get(u.get("id"), []) else "n"}">'
                f'{"✓" if k in covered.get(u.get("id"), []) else "·"}</td>' for k in kinds)
            rows.append(f'<tr><td>{_e(u.get("title") or u.get("id"))}</td>{cells}</tr>')
        parts.append(f'<div class="tblwrap"><table><thead><tr><th>Requirement</th>{th}</tr></thead>'
                     f'<tbody>{"".join(rows)}</tbody></table></div>')
    if not parts:
        return ("<p class='muted'>No coverage matrix recorded — run <code>get_coverage</code> after "
                "implement to build the requirement × kind traceability matrix.</p>")
    return ('<p class="lead">Requirement × test-kind traceability, plus how much of the reachable code the '
            'scenarios name. Gaps here feed §7.</p>' + "\n".join(parts))


def _sec_gaps(cov, open_questions) -> str:
    cov_gaps = cov.get("gaps") or []
    items: list[str] = []
    for g in cov_gaps:
        miss = ", ".join(g.get("missing", [])) if isinstance(g, dict) else ""
        title = g.get("title") or g.get("id") if isinstance(g, dict) else str(g)
        items.append(f"{title}" + (f" — missing: {miss}" if miss else ""))
    dev_items = [q.question for q in open_questions]
    if not items and not dev_items:
        return ("<p class='muted'>No open spec gaps or dev-confirmation items — the brief resolved every "
                "question and the matrix is fully covered.</p>")
    out = [('<p class="lead">Where the spec is silent or ambiguous. Each item needs a developer/PO decision '
            'before the affected scenarios can be trusted.</p>')]
    if dev_items:
        out.append("<h3>Dev-confirmation items (unanswered questions)</h3>")
        out.append("<div class='gaps'>")
        for q in open_questions:
            why = f'<div class="d-why">{_e(q.why)}</div>' if q.why else ""
            rec = f'<div class="d-chosen"><b>Suggested:</b> {_e(q.recommendation)}</div>' if q.recommendation else ""
            out.append(f'<div class="gapcard"><div class="d-stmt">{_e(q.question)}</div>{why}{rec}</div>')
        out.append("</div>")
        out.append(_gap_mermaid(dev_items))
    if items:
        out.append("<h3>Coverage gaps (requirement × kind not yet covered)</h3>")
        out.append("<ul class='tight'>" + "".join(f"<li>{_e(x)}</li>" for x in items) + "</ul>")
    return "\n".join(out)


def _sec_oos(plan) -> str:
    oos = (plan.out_of_scope if plan else []) or []
    if not oos:
        return "<p class='muted'>Nothing was explicitly excluded from this plan.</p>"
    lst = "".join(f"<li>{_e(x)}</li>" for x in oos)
    return ('<p class="lead">Deliberately excluded from this plan and why — everything outside the '
            'confirmed boundary below.</p>'
            f"<ul class='scopelist scope-out'>{lst}</ul>"
            + _oos_mermaid(plan.scope if plan else [], oos))


def _bench_table(components: dict, meta: dict) -> str:
    rows = []
    for key, (label, weight, desc) in meta.items():
        val = components.get(key) if components else None
        contrib = f"{weight * float(val):.3f}" if isinstance(val, (int, float)) else "&mdash;"
        rows.append(
            f'<tr><td><b>{_e(label)}</b></td><td class="mono">{weight:.2f}</td>'
            f'<td class="mono {_grade(val)}">{_fmt(val)}</td><td class="mono">{contrib}</td>'
            f'<td class="cell-desc">{_e(desc)}</td></tr>')
    return ('<div class="tblwrap"><table><thead><tr><th>Component</th><th>Weight</th><th>Score</th>'
            f'<th>Contribution</th><th>What it measures</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>')


def _sec_bench(assured: dict, bench) -> str:
    parts = [('<p class="lead">Scores from the Test-Evaluation agent (read-only quality gate). PQS grades '
              'the knowledge pack; TPS grades the test plan &amp; suite. Both are 0&ndash;1, weighted from '
              'the components below.</p>')]
    pqs = getattr(bench, "pqs", None) if bench else None
    tps = getattr(bench, "tps", None) if bench else None
    parts.append('<div class="bmrow">'
                 f'<div class="score {_grade(pqs)}"><div class="n">{_fmt(pqs)}</div><div class="l">PQS — pack quality</div></div>'
                 f'<div class="score {_grade(tps)}"><div class="n">{_fmt(tps)}</div><div class="l">TPS — test plan &amp; suite</div></div></div>')
    if bench is None:
        parts.append('<p class="muted">Not yet scored — run <code>evaluate_pack</code> and '
                     '<code>evaluate_plan</code>. The rubric and weights below still apply.</p>')
    parts.append("<h3>PQS — Pack Quality Score</h3>")
    parts.append(_bench_table(getattr(bench, "pqs_components", {}) if bench else {}, _PQS_META))
    parts.append("<h3>TPS — Test-Plan Score</h3>")
    parts.append(_bench_table(getattr(bench, "tps_components", {}) if bench else {}, _TPS_META))
    if bench is not None and getattr(bench, "retrieval", None):
        r = bench.retrieval or {}
        parts.append("<h3>Retrieval highlights (pack)</h3><div class='tblwrap'><table><tbody>"
                     f"<tr><td>precision</td><td class='mono'>{_fmt(r.get('precision'))}</td></tr>"
                     f"<tr><td>recall</td><td class='mono'>{_fmt(r.get('recall'))}</td></tr>"
                     f"<tr><td>leaked (hard-neg)</td><td class='mono'>{_e(r.get('leaked'))}</td></tr>"
                     "</tbody></table></div>")
    # assured-generation loop (define/implement gate) — separate from TEV
    score = assured.get("final_score")
    if score is not None:
        accepted = assured.get("accepted")
        iters = assured.get("iterations") or []
        parts.append("<h3>Assured-generation loop</h3>")
        parts.append('<div class="bmrow">'
                     f'<div class="score {"good" if accepted else "bad"}"><div class="n">{score:.2f}</div>'
                     '<div class="l">assured score</div></div>'
                     + (f'<div class="score"><div class="n">{assured.get("threshold"):.2f}</div>'
                        '<div class="l">pass bar</div></div>' if assured.get("threshold") is not None else "")
                     + f'<div class="score"><div class="n">{len(iters)}</div><div class="l">rounds</div></div>'
                     + f'<div class="score"><div class="n">{"yes" if accepted else "no"}</div>'
                       '<div class="l">accepted</div></div></div>')
        issues = assured.get("issues") or []
        if issues:
            parts.append("<p><b>Judge criticism:</b></p><ul class='tight'>"
                         + "".join(f"<li>{_e(x)}</li>" for x in issues[:12]) + "</ul>")
    return "\n".join(parts)


def _sec_deliver(scenarios, steps_by, test_data, cov_md, ctx, feature) -> str:
    # full-suite downloads (self-contained). Prefer the canonical persisted .feature; fall back to a
    # per-scenario render only when export_features never ran for this run.
    feat = feature or "\n\n".join(
        "Feature: " + sc.title + "\n\n  " + _gherkin_one(sc, steps_by.get(sc.id, [])).replace("\n", "\n  ")
        for sc in _ordered(scenarios))
    all_data = {td.id.split(":")[-1]: td.spec for td in test_data}
    dls = [_download("all feature files (.feature)", f"{ctx}.feature", feat, mime="text/plain")
           if scenarios else "",
           _download("all test data (.json)", f"{ctx}-testdata.json",
                     json.dumps(all_data, ensure_ascii=False, indent=2)) if test_data else "",
           _download("coverage matrix (.md)", f"{ctx}-coverage.md", cov_md, mime="text/markdown")
           if cov_md else ""]
    dlrow = "".join(d for d in dls if d) or "<span class='muted'>—</span>"
    delivered = [
        f"{len(scenarios)} BDD test scenarios with detailed, oracle-bearing steps (§5)",
        f"{len(test_data)} downloadable test-data fixtures (§5)",
        "Executable Gherkin feature files (download below)",
        "Requirement × test-kind coverage matrix (§6)" if cov_md else None,
        "TEV quality scorecard: PQS + TPS (§9)",
        "This self-contained QA/QC test-plan report",
    ]
    steps_next = [
        "Resolve the dev-confirmation items in §7, then re-run define → implement for the affected cases.",
        "Execute the suite against the target environment and capture pass/fail + evidence.",
        "Feed real execution results back to raise fault-detection & oracle-strength (§9).",
        "Re-score with evaluate_pack / evaluate_plan and compare runs to track quality over time.",
    ]
    return (
        '<h3>Deliverables</h3><ul class="tight">'
        + "".join(f"<li>{_e(x)}</li>" for x in delivered if x)
        + f'</ul><div class="dlrow">{dlrow}</div>'
        '<h3>Next steps</h3><ol class="tight">'
        + "".join(f"<li>{_e(x)}</li>" for x in steps_next) + "</ol>")


# ---- assembly --------------------------------------------------------------------------------------
def build_report_html(bank, context_id: str) -> str:
    """Render the 10-section QA/QC test-plan report for `context_id` from the persisted run."""
    plan = store.read_plan(bank, context_id)
    brief = store.read_plan_brief(bank, context_id) or store.read_implement_brief(bank, context_id)
    decisions = store.read_decisions(bank, context_id)
    scenarios = store.read_scenarios(bank, context_id)
    steps = store.read_steps(bank, context_id)
    test_data = store.read_test_data(bank, context_id)
    cov = store.read_coverage(bank, context_id)
    cov_md = store.read_coverage_md(bank, context_id)
    feature = store.read_feature(bank, context_id, context_id)
    assured = store.read_assured_state(bank, context_id) or {}
    questions = store.read_questions(bank, context_id)
    answers = store.read_answers(bank, context_id)
    try:
        from common.benchmark.store import read_benchmark
        bench = read_benchmark(bank, context_id)
    except Exception:  # noqa: BLE001 — benchmark is optional; never fail the report on it
        bench = None

    steps_by = _steps_by_scenario(steps)
    td_by_id = {td.id: td for td in test_data}
    answered = {a.question_id for a in answers}
    open_q = [q for q in questions if q.id not in answered or getattr(q, "status", "") == "open"]
    keys = _all_jira_keys([context_id], plan.source_refs if plan else [],
                          *[d.source_refs for d in decisions])

    bodies = {
        "s-summary": _sec_summary(plan, brief, scenarios, keys, test_data),
        "s-arch": _sec_arch(cov, plan),
        "s-decisions": _sec_decisions(decisions),
        "s-method": _sec_method(plan),
        "s-scenarios": _sec_scenarios(scenarios, steps_by, td_by_id),
        "s-coverage": _sec_coverage(cov, cov_md),
        "s-gaps": _sec_gaps(cov, open_q),
        "s-oos": _sec_oos(plan),
        "s-bench": _sec_bench(assured, bench),
        "s-deliver": _sec_deliver(scenarios, steps_by, test_data, cov_md, context_id, feature),
    }

    nav, secs = _nav_and_sections(_SECTIONS, bodies)
    ticket = keys[0] if keys else context_id
    header = (
        '<header><div class="eyebrow">Testing Agent &middot; QA/QC Test Plan</div>'
        f'<h1>Test plan &mdash; {_e(ticket)}</h1>'
        f'<div class="meta"><span><b>Context</b> <span class="mono">{_e(context_id)}</span></span>'
        f'<span><b>Scenarios</b> {len(scenarios)}</span>'
        f'<span><b>Methodology</b> {_e(", ".join(plan.methodology) if plan and plan.methodology else "—")}</span>'
        '</div></header>')
    footer = (f"Testing Agent QA/QC test plan &middot; context {_e(context_id)} &middot; "
              "deterministically rendered from the persisted run.")
    return _page(f"Test Plan - {ticket}", header, nav, secs, footer)
