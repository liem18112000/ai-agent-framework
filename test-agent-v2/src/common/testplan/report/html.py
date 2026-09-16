"""Deterministic enriched HTML test report, rendered from the persisted run in the memory bank.

One self-contained page with tabs: Scenarios, Feature files (Gherkin), Test data, Benchmark, and a
per-test-case Workflow walkthrough (each case's step flow + an explanation of what it verifies). Pure
render — reads via `common.testplan.memory` only, no writes, no `test_plan_definition` import."""

from __future__ import annotations

import html as _html

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


def _e(s) -> str:
    return _html.escape(str(s) if s is not None else "")


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


# ---- tabs ------------------------------------------------------------------------------------------
def _scenarios_tab(scenarios, steps_by) -> str:
    if not scenarios:
        return "<p class='muted'>No scenarios generated for this run.</p>"
    out = []
    for sc in _ordered(scenarios):
        oracle = ""
        sts = steps_by.get(sc.id, [])
        # the last Then/And step (or expected) is the effective oracle
        then = [s for s in sts if s.keyword.lower() in ("then", "and")] or sts
        if then:
            oracle = then[-1].expected or then[-1].action
        out.append(
            f'<div class="sc"><div class="sc-head">{_chip(sc.kind)}'
            f'<span class="sc-title">{_e(sc.title)}</span></div>'
            + (f'<p class="sc-desc">{_e(sc.description)}</p>' if sc.description else "")
            + (f'<p class="sc-why"><b>Why:</b> {_e(sc.rationale)}</p>' if sc.rationale else "")
            + (f'<div class="oracle"><span class="tag">oracle</span>{_e(oracle)}</div>' if oracle else "")
            + "</div>")
    return "\n".join(out)


def _gherkin(scenarios, steps_by) -> str:
    """Inline Gherkin, one Feature block per kind (kept in common — no TPD import)."""
    from collections import defaultdict
    groups: dict = defaultdict(list)
    for sc in _ordered(scenarios):
        groups[sc.kind].append(sc)
    blocks = []
    for kind, scs in groups.items():
        lines = [f"Feature: {kind} scenarios"]
        for sc in scs:
            lines.append(f"\n  @{sc.kind} @{sc.methodology}")
            lines.append(f"  Scenario: {sc.title}")
            sts = steps_by.get(sc.id, [])
            if sts:
                for st in sts:
                    kw = st.keyword or "When"
                    lines.append(f"    {kw} {st.action}")
                    if st.expected and not st.keyword:
                        lines.append(f"    Then {st.expected}")
            else:
                for p in sc.preconditions:
                    lines.append(f"    Given {p}")
                if sc.description:
                    lines.append(f"    When {sc.description}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _features_tab(scenarios, steps_by) -> str:
    if not scenarios:
        return "<p class='muted'>No scenarios to export as feature files.</p>"
    text = _gherkin(scenarios, steps_by)
    return (f'<p class="lead">Executable Gherkin generated from the scenarios + steps, grouped by kind.</p>'
            f'<pre class="gherkin"><code>{_e(text)}</code></pre>')


def _testdata_tab(test_data) -> str:
    if not test_data:
        return "<p class='muted'>No test-data partitions recorded for this run.</p>"
    rows = []
    for td in test_data:
        spec = td.spec if isinstance(td.spec, dict) else {}
        detail = _e("; ".join(f"{k}={v}" for k, v in spec.items())) if spec else "&mdash;"
        rows.append(f'<tr><td class="mono">{_e(td.id.split(":")[-1])}</td>'
                    f'<td class="mono">{_e(td.kind)}</td><td>{detail}</td></tr>')
    return ('<p class="lead">Test-data partitions / fixtures for this run.</p>'
            '<div class="tblwrap"><table><thead><tr><th>Id</th><th>Kind</th><th>Spec</th></tr>'
            f'</thead><tbody>{"".join(rows)}</tbody></table></div>')


def _benchmark_tab(assured: dict, bench) -> str:
    parts = []
    score = assured.get("final_score")
    bar = assured.get("threshold")
    accepted = assured.get("accepted")
    iters = assured.get("iterations") or []
    if score is not None:
        cls = "good" if accepted else "bad"
        parts.append('<div class="bmrow">'
                     f'<div class="score {cls}"><div class="n">{score:.2f}</div>'
                     '<div class="l">Assured score</div></div>'
                     + (f'<div class="score bar"><div class="n">{bar:.2f}</div><div class="l">Pass bar</div></div>'
                        if bar is not None else "")
                     + f'<div class="score bar"><div class="n">{len(iters)}</div><div class="l">Rounds</div></div>'
                     + f'<div class="score bar"><div class="n">{"yes" if accepted else "no"}</div>'
                       '<div class="l">Accepted</div></div></div>')
        verdict = "good" if accepted else "bad"
        parts.append(f'<p><span class="pill {verdict}">{"above bar" if accepted else "below bar"}</span> '
                     f'{_e(assured.get("note") or "")}</p>')
        issues = assured.get("issues") or []
        if issues:
            parts.append("<h3>Judge criticism</h3><ul class='tight'>"
                         + "".join(f"<li>{_e(i)}</li>" for i in issues[:12]) + "</ul>")
    if bench is not None:
        r = getattr(bench, "retrieval", None) or {}
        parts.append("<h3>TEV scorecard</h3><div class='tblwrap'><table><tbody>"
                     f"<tr><td>PQS</td><td class='mono'>{_e(getattr(bench,'pqs',None))}</td></tr>"
                     f"<tr><td>TPS</td><td class='mono'>{_e(getattr(bench,'tps',None))}</td></tr>"
                     f"<tr><td>retrieval precision</td><td class='mono'>{_e(r.get('precision'))}</td></tr>"
                     f"<tr><td>retrieval recall</td><td class='mono'>{_e(r.get('recall'))}</td></tr>"
                     f"<tr><td>leaked (hard-neg)</td><td class='mono'>{_e(r.get('leaked'))}</td></tr>"
                     "</tbody></table></div>")
    if not parts:
        return "<p class='muted'>No benchmark/assured data recorded for this run.</p>"
    return "\n".join(parts)


def _workflow_tab(scenarios, steps_by) -> str:
    """Per-test-case walkthrough: each case's step flow + an explanation of what it verifies."""
    if not scenarios:
        return "<p class='muted'>No test cases to walk through.</p>"
    out = ['<p class="lead">Case-by-case flow &mdash; follow each test\'s steps in order and what each '
           'one verifies.</p>']
    for i, sc in enumerate(_ordered(scenarios), 1):
        sts = steps_by.get(sc.id, [])
        flow = []
        if sts:
            for st in sts:
                kw = _e(st.keyword or "step")
                exp = f'<div class="fl-exp">&rarr; {_e(st.expected)}</div>' if st.expected else ""
                flow.append(f'<div class="fl-step"><span class="fl-kw">{kw}</span>'
                            f'<div class="fl-body"><div class="fl-act">{_e(st.action)}</div>{exp}</div></div>')
        else:
            # no detailed steps — synthesise the flow from the scenario fields
            for p in sc.preconditions:
                flow.append(f'<div class="fl-step"><span class="fl-kw">given</span>'
                            f'<div class="fl-body"><div class="fl-act">{_e(p)}</div></div></div>')
            if sc.description:
                flow.append(f'<div class="fl-step"><span class="fl-kw">verify</span>'
                            f'<div class="fl-body"><div class="fl-act">{_e(sc.description)}</div></div></div>')
        why = " ".join(x for x in (sc.description, sc.rationale) if x) or "Exercises the behaviour under test."
        out.append(
            f'<div class="wf"><div class="wf-head"><span class="wf-n">{i}</span>{_chip(sc.kind)}'
            f'<span class="wf-title">{_e(sc.title)}</span></div>'
            f'<p class="wf-why">{_e(why)}</p>'
            f'<div class="fl">{"".join(flow) or "<span class=muted>No steps.</span>"}</div></div>')
    return "\n".join(out)


def build_report_html(bank, context_id: str) -> str:
    """Render the enriched HTML report for `context_id` from the persisted run. Self-contained page."""
    plan = store.read_plan(bank, context_id)
    scenarios = store.read_scenarios(bank, context_id)
    steps = store.read_steps(bank, context_id)
    test_data = store.read_test_data(bank, context_id)
    assured = store.read_assured_state(bank, context_id) or {}
    try:
        from common.benchmark.store import read_benchmark
        bench = read_benchmark(bank, context_id)
    except Exception:  # noqa: BLE001 — benchmark is optional; never fail the report on it
        bench = None
    steps_by = _steps_by_scenario(steps)

    scope = "".join(f"<li>{_e(x)}</li>" for x in (plan.scope if plan else []))
    oos = "".join(f"<li>{_e(x)}</li>" for x in (plan.out_of_scope if plan else []))
    method = _e(", ".join(plan.methodology) if plan else "")
    kinds = _e(", ".join(effective_kinds(plan)) if plan else "happy, negative, boundary, error")

    return _SHELL.format(
        ctx=_e(context_id), n=len(scenarios), method=method or "&mdash;", kinds=kinds,
        css=_CSS,
        scope=(f"<ul class='scopelist scope-in'>{scope}</ul>" if scope else "<p class='muted'>&mdash;</p>"),
        oos=(f"<ul class='scopelist scope-out'>{oos}</ul>" if oos else "<p class='muted'>&mdash;</p>"),
        scenarios=_scenarios_tab(scenarios, steps_by),
        features=_features_tab(scenarios, steps_by),
        testdata=_testdata_tab(test_data),
        benchmark=_benchmark_tab(assured, bench),
        workflow=_workflow_tab(scenarios, steps_by),
    )


_CSS = """
:root{--bg:#f4f6f6;--surface:#fff;--surface-2:#eef2f2;--ink:#12201f;--ink-2:#3a4d4b;--muted:#63807c;
--line:#d7e0de;--accent:#0f766e;--accent-soft:#d5ebe7;--good:#0f766e;--bad:#b42318;--warn:#9a6a00;
--k-happy:#0f766e;--k-happy-bg:#d5ede9;--k-negative:#9a6a00;--k-negative-bg:#f6ead0;
--k-boundary:#1d5fb8;--k-boundary-bg:#dce8fb;--k-error:#b42318;--k-error-bg:#f8dcd8;
--k-security:#6b3fa0;--k-security-bg:#e8def7;--k-concurrency:#0e7490;--k-concurrency-bg:#d3eef4;
--k-encoding:#a83287;--k-encoding-bg:#f6dcef;--k-perf:#7a5b1e;--k-perf-bg:#f0e6cf;
--k-other:#4b5a58;--k-other-bg:#e5ecea;--scope-in:#0f766e;--scope-out:#8a5a2b;
--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;--sans:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;}
@media(prefers-color-scheme:dark){:root{--bg:#0d1514;--surface:#141f1e;--surface-2:#182524;--ink:#e6efed;
--ink-2:#b6c7c4;--muted:#7f9995;--line:#263634;--accent:#4fd1c5;--accent-soft:#123330;--good:#5fd6c8;--bad:#f0917f;--warn:#e0b562;
--k-happy:#5fd6c8;--k-happy-bg:#10312d;--k-negative:#e0b562;--k-negative-bg:#33280f;
--k-boundary:#7db0f5;--k-boundary-bg:#122744;--k-error:#f0917f;--k-error-bg:#3a1712;
--k-security:#c1a0ec;--k-security-bg:#251437;--k-concurrency:#63c6dc;--k-concurrency-bg:#0e2f38;
--k-encoding:#e59cd0;--k-encoding-bg:#361029;--k-perf:#d8b877;--k-perf-bg:#2c2410;
--k-other:#9fb2af;--k-other-bg:#1c2827;--scope-in:#5fd6c8;--scope-out:#e0b562;}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);line-height:1.55}
.wrap{max-width:960px;margin:0 auto;padding:40px 24px 96px}
.eyebrow{font-size:12px;letter-spacing:.16em;text-transform:uppercase;color:var(--muted);font-weight:600}
h1{font-size:29px;margin:.3em 0 .1em;letter-spacing:-.01em}h2{font-size:19px;margin:1.8em 0 .3em;border-bottom:1px solid var(--line);padding-bottom:.3em}
h3{font-size:14px;color:var(--ink-2);margin:1.3em 0 .4em}p{margin:.5em 0}.muted{color:var(--muted)}
.mono{font-family:var(--mono)}.lead{color:var(--ink-2);font-size:14px;max-width:70ch}
.meta{display:flex;flex-wrap:wrap;gap:6px 20px;margin-top:12px;color:var(--ink-2);font-size:13px}.meta b{color:var(--ink)}
.tabs{position:sticky;top:0;z-index:5;display:flex;flex-wrap:wrap;gap:4px;margin:20px 0 6px;padding:8px 0;background:var(--bg);border-bottom:1px solid var(--line)}
.tab-btn{font:600 13px var(--sans);color:var(--ink-2);background:none;border:1px solid transparent;border-radius:8px;padding:7px 13px;cursor:pointer}
.tab-btn:hover{background:var(--surface-2)}.tab-btn[aria-selected=true]{background:var(--accent-soft);color:var(--accent);border-color:var(--line)}
.tab-btn:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.panel-tab{display:none}.panel-tab.active{display:block}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:6px}@media(max-width:640px){.grid2{grid-template-columns:1fr}}
.box{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px 16px}.box h3{margin-top:0}
.scopelist{list-style:none;margin:.2em 0;padding:0}.scopelist li{position:relative;padding-left:1.4em;margin:.35em 0;font-size:13.5px;color:var(--ink-2)}
.scopelist li::before{position:absolute;left:0;font-weight:700}.scope-in li::before{content:"+";color:var(--scope-in)}.scope-out li::before{content:"\\2013";color:var(--scope-out)}
.chip{display:inline-flex;align-items:center;font-size:11px;font-weight:600;letter-spacing:.03em;text-transform:uppercase;padding:3px 9px;border-radius:999px;white-space:nowrap}
.chip.happy{color:var(--k-happy);background:var(--k-happy-bg)}.chip.negative{color:var(--k-negative);background:var(--k-negative-bg)}
.chip.boundary{color:var(--k-boundary);background:var(--k-boundary-bg)}.chip.error{color:var(--k-error);background:var(--k-error-bg)}
.chip.security{color:var(--k-security);background:var(--k-security-bg)}.chip.concurrency{color:var(--k-concurrency);background:var(--k-concurrency-bg)}
.chip.encoding{color:var(--k-encoding);background:var(--k-encoding-bg)}.chip.perf{color:var(--k-perf);background:var(--k-perf-bg)}
.chip.other{color:var(--k-other);background:var(--k-other-bg)}
.sc{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:13px 15px;margin:10px 0}
.sc-head{display:flex;align-items:baseline;gap:9px;flex-wrap:wrap;margin-bottom:6px}.sc-title{font-size:14.5px;font-weight:650}
.sc-desc{font-size:13.5px;color:var(--ink-2);margin:.3em 0}.sc-why{font-size:13px;color:var(--muted);margin:.2em 0}
.oracle{margin-top:8px;padding-top:8px;border-top:1px dashed var(--line);font-size:13px;color:var(--ink-2)}
.oracle .tag{font:700 10.5px var(--mono);letter-spacing:.09em;text-transform:uppercase;color:var(--accent);margin-right:.5em}
.gherkin{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px;overflow-x:auto;font:12.5px/1.5 var(--mono);color:var(--ink-2)}
table{width:100%;border-collapse:collapse;font-size:13.5px}.tblwrap{overflow-x:auto}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);vertical-align:top}th{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
td.mono{font-family:var(--mono);font-size:12.5px;color:var(--ink-2)}
.bmrow{display:flex;flex-wrap:wrap;gap:14px;margin:8px 0}
.score{background:var(--surface);border:1px solid var(--line);border-left:4px solid var(--muted);border-radius:10px;padding:12px 18px;min-width:120px}
.score.good{border-left-color:var(--good)}.score.bad{border-left-color:var(--bad)}
.score .n{font-size:30px;font-weight:700;font-variant-numeric:tabular-nums}.score.good .n{color:var(--good)}.score.bad .n{color:var(--bad)}
.score .l{font-size:11px;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);margin-top:3px}
.pill{display:inline-block;font-size:11px;font-weight:700;text-transform:uppercase;padding:2px 9px;border-radius:999px}
.pill.good{color:var(--good);background:var(--k-happy-bg)}.pill.bad{color:var(--bad);background:var(--k-error-bg)}
ul.tight{margin:.3em 0;padding-left:1.15em}ul.tight li{margin:.25em 0;font-size:13.5px;color:var(--ink-2)}
.wf{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:12px 0}
.wf-head{display:flex;align-items:center;gap:9px;flex-wrap:wrap}.wf-n{font:700 12px var(--mono);color:#fff;background:var(--accent);border-radius:6px;padding:1px 7px}
.wf-title{font-size:14.5px;font-weight:650}.wf-why{font-size:13px;color:var(--ink-2);margin:.5em 0 .7em}
.fl{display:flex;flex-direction:column;gap:0}
.fl-step{display:flex;gap:10px;padding:7px 0;position:relative}
.fl-step:not(:last-child)::after{content:"";position:absolute;left:52px;top:26px;bottom:-3px;width:2px;background:var(--line)}
.fl-kw{flex:0 0 auto;align-self:flex-start;font:700 10.5px var(--mono);text-transform:uppercase;letter-spacing:.06em;color:var(--accent);background:var(--accent-soft);border:1px solid var(--line);border-radius:6px;padding:3px 8px;min-width:74px;text-align:center}
.fl-body{flex:1 1 auto}.fl-act{font-size:13.5px;color:var(--ink)}.fl-exp{font-size:12.5px;color:var(--muted);margin-top:2px}
footer{margin-top:48px;padding-top:16px;border-top:1px solid var(--line);color:var(--muted);font-size:12px}
"""

_SHELL = """<title>Test Report - {ctx}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>{css}</style>
<div class="wrap">
  <header>
    <div class="eyebrow">Testing Agent &middot; Test Report</div>
    <h1>Test scenarios &amp; execution report</h1>
    <div class="meta"><span><b>Context</b> <span class="mono">{ctx}</span></span>
      <span><b>Scenarios</b> {n}</span><span><b>Methodology</b> {method}</span>
      <span><b>Kinds</b> {kinds}</span></div>
  </header>
  <div class="grid2" style="margin-top:14px">
    <div class="box"><h3>In scope</h3>{scope}</div>
    <div class="box"><h3>Out of scope</h3>{oos}</div>
  </div>
  <div class="tabs" role="tablist" aria-label="Report sections">
    <button class="tab-btn" role="tab" aria-selected="true" data-tab="t-scen">Scenarios</button>
    <button class="tab-btn" role="tab" aria-selected="false" data-tab="t-feat">Feature files</button>
    <button class="tab-btn" role="tab" aria-selected="false" data-tab="t-data">Test data</button>
    <button class="tab-btn" role="tab" aria-selected="false" data-tab="t-bm">Benchmark</button>
    <button class="tab-btn" role="tab" aria-selected="false" data-tab="t-flow">Workflow</button>
  </div>
  <section id="t-scen" class="panel-tab active" role="tabpanel"><h2>Scenarios</h2>{scenarios}</section>
  <section id="t-feat" class="panel-tab" role="tabpanel"><h2>Feature files</h2>{features}</section>
  <section id="t-data" class="panel-tab" role="tabpanel"><h2>Test data</h2>{testdata}</section>
  <section id="t-bm" class="panel-tab" role="tabpanel"><h2>Benchmark</h2>{benchmark}</section>
  <section id="t-flow" class="panel-tab" role="tabpanel"><h2>Test-case workflow</h2>{workflow}</section>
  <footer>Testing Agent enriched report &middot; context {ctx} &middot; generated from the persisted run.</footer>
</div>
<script>
  var b=[].slice.call(document.querySelectorAll('.tab-btn'));
  function show(id){{b.forEach(function(x){{var on=x.dataset.tab===id;x.setAttribute('aria-selected',on);
    document.getElementById(x.dataset.tab).classList.toggle('active',on);}});}}
  b.forEach(function(x){{x.addEventListener('click',function(){{show(x.dataset.tab);}});}});
</script>"""
