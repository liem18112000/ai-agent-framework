"""Deterministic PLAN-PREVIEW report — the test plan as decided at `define_plan`, rendered from the
persisted plan + decisions BEFORE any scenarios are generated. The OPTIONAL step run after define_plan
and BEFORE the user approves the plan (`approve_plan`), so the human can eyeball the methodology, scope
decisions, in/out-of-scope and any unresolved questions before signing off — the plan-stage twin of the
knowledge preview (which sits before `approve`).

Five sections: 1. Summary   2. Confirmed scope decisions   3. Methodology & test-design
               4. Scope (in / out)   5. Open questions to resolve.

Pure render — reads the memory bank only; no writes, no agent import. Reuses the shared stylesheet /
page shell (`common.report.util`) AND the plan-stage section builders from the final test-plan report
(`common.testplan.report.html`) so the preview and the final deliverable stay visually identical — no
scenario / coverage / benchmark sections, which don't exist yet at this stage."""

from __future__ import annotations

from common.interrogate.pack import load_pack
from common.report import util as ru
from common.testplan import memory as store
from common.testplan.models import effective_kinds
from common.testplan.report.html import _sec_decisions, _sec_method, _sec_oos

_SECTIONS = [
    ("p-summary", "Summary"),
    ("p-decisions", "Confirmed scope decisions"),
    ("p-method", "Methodology & test-design"),
    ("p-scope", "Scope (in / out)"),
    ("p-open", "Open questions to resolve"),
]


def _sec_summary(plan, brief, keys) -> str:
    method = ", ".join(plan.methodology) if plan and plan.methodology else "&mdash;"
    kinds = ", ".join(effective_kinds(plan)) if plan else "happy, negative, boundary, error"
    conf = plan.confidence if plan else "&mdash;"
    tickets = " ".join(ru.jira_link(k) for k in keys) or "&mdash;"
    scope = "".join(f"<li>{ru.e(x)}</li>" for x in (plan.scope if plan else []))
    summary_html = ru.md(brief) if brief else (
        f"<ul class='scopelist scope-in'>{scope}</ul>" if scope else "<p class='muted'>&mdash;</p>")
    return (
        '<p class="lead">The test plan as defined — review the methodology, scope calls and open '
        'questions <b>before approving</b>. Test scenarios are generated after approval.</p>'
        f'<div class="box">{summary_html}</div>'
        '<div class="kv">'
        f'<div><span class="k">Ticket(s)</span><span class="v">{tickets}</span></div>'
        f'<div><span class="k">Test service / methodology</span><span class="v">{ru.e(method)}</span></div>'
        f'<div><span class="k">Test kinds</span><span class="v">{ru.e(kinds)}</span></div>'
        f'<div><span class="k">Plan confidence</span><span class="v">{ru.e(conf)}</span></div>'
        '</div>')


def _sec_scope(plan) -> str:
    scope = (plan.scope if plan else []) or []
    in_html = ("<ul class='scopelist scope-in'>" + "".join(f"<li>{ru.e(x)}</li>" for x in scope) +
               "</ul>") if scope else "<p class='muted'>No in-scope items recorded.</p>"
    return "<h3>In scope</h3>" + in_html + "<h3>Out of scope</h3>" + _sec_oos(plan)


def _sec_open(open_q) -> str:
    if not open_q:
        return "<p class='muted'>No unresolved questions — every define-stage question was answered.</p>"
    items = "".join(
        f"<li><b>{ru.e(q.question)}</b>"
        + (f' <span class="muted">— {ru.e(q.why)}</span>' if getattr(q, "why", "") else "")
        + "</li>"
        for q in open_q)
    return ('<p class="lead">Still open from the define stage — resolve or accept these before '
            'approving the plan.</p>'
            f"<ul class='tight'>{items}</ul>")


def build_plan_preview_html(bank, context_id: str) -> str:
    """Render the 5-section plan-preview report for `context_id` from the persisted plan + decisions."""
    plan = store.read_plan(bank, context_id)
    brief = store.read_plan_brief(bank, context_id)
    decisions = store.read_decisions(bank, context_id)
    questions = store.read_questions(bank, context_id)
    answers = store.read_answers(bank, context_id)
    answered = {a.question_id for a in answers}
    open_q = [q for q in questions if q.id not in answered or getattr(q, "status", "") == "open"]

    # Title by the run's SUBJECT ticket — the pack's grounded Jira nodes, the same signal the knowledge
    # preview uses — NOT the plan/decision source_refs, which are dominated by out-of-scope references
    # (an out-of-scope decision cites the excluded ticket). Keeps all three reports titled consistently.
    pack = load_pack(bank, context_id)
    keys = ru.all_jira_keys([context_id, pack.seed], [n.id for n in pack.grounded])
    ticket = keys[0] if keys else context_id

    bodies = {
        "p-summary": _sec_summary(plan, brief, keys),
        "p-decisions": _sec_decisions(decisions),
        "p-method": _sec_method(plan),
        "p-scope": _sec_scope(plan),
        "p-open": _sec_open(open_q),
    }
    nav, secs = ru.nav_and_sections(_SECTIONS, bodies)
    header = (
        '<header><div class="eyebrow">Testing Agent &middot; Plan Preview</div>'
        f'<h1>Plan preview &mdash; {ru.e(ticket)}</h1>'
        f'<div class="meta"><span><b>Context</b> <span class="mono">{ru.e(context_id)}</span></span>'
        f'<span><b>Decisions</b> {len(decisions)}</span>'
        f'<span><b>Open questions</b> {len(open_q)}</span></div>'
        '<p class="lead">A preview of the defined test plan for you to review <b>before approving</b> '
        '(approve_plan). Scenarios are generated after approval.</p></header>')
    footer = f"Testing Agent plan preview &middot; context {ru.e(context_id)}"
    return ru.page(f"Plan Preview - {ticket}", header, nav, secs, footer)
