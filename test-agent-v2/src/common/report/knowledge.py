"""Deterministic knowledge-PREVIEW report — how the Knowledge-Gathering Agent understands the ticket,
rendered from the persisted pack. The OPTIONAL step run after `refine` and BEFORE the user approves, so
the human can eyeball what was gathered, the gaps, and the hard concepts (with diagrams) before signing off.

One self-contained, printable, theme-aware page with a sticky section nav and 6 sections:
  1. Understanding & summary   2. Knowledge map (mermaid)   3. Key concepts explained (with diagrams)
  4. Gaps & open questions     5. Sources & provenance      6. Pack quality (PQS, optional)

Pure render — reads the memory bank only; no writes, no agent import. Diagrams use `<pre class="mermaid">`
(renders in a browser via the inlined loader and natively in the Artifact viewer); shares every generic
render helper + the stylesheet with the test-plan report via `common.report.util`."""

from __future__ import annotations

from collections import defaultdict

from common.interrogate.pack import load_pack
from common.models.graph import (
    ATTACHMENT,
    BITBUCKET,
    CODEGRAPH,
    CONFLUENCE_PAGE,
    EXTERNAL_WEB,
    JIRA_ISSUE,
)
from common.models.refine import INSIGHT
from common.report import util as ru

# node type -> (css chip class, friendly label). Unknown -> ("other", the raw type).
_KIND = {
    JIRA_ISSUE: ("jira", "Jira"),
    CONFLUENCE_PAGE: ("confluence", "Confluence"),
    BITBUCKET: ("code", "Code"),
    CODEGRAPH: ("code", "Codegraph"),
    ATTACHMENT: ("attachment", "Attachment"),
    EXTERNAL_WEB: ("web", "Web"),
    INSIGHT: ("insight", "Insight"),
}

_SECTIONS = [
    ("k-understanding", "Understanding & summary"),
    ("k-map", "Knowledge map"),
    ("k-concepts", "Key concepts explained"),
    ("k-gaps", "Gaps & open questions"),
    ("k-sources", "Sources & provenance"),
    ("k-quality", "Pack quality"),
]


def _kind(note) -> tuple[str, str]:
    return _KIND.get(note.type, ("other", (note.type or "node").replace("-", " ")))


def _chip(note) -> str:
    cls, label = _kind(note)
    return f'<span class="chip {cls}">{ru.e(label)}</span>'


def _note_link(note) -> str:
    """Best clickable link for a note: its source_url, else a followed link, else a jira browse link."""
    url = note.source_url or next((lr.canonical_url or lr.url for lr in note.links if lr.in_scope), "")
    if ru.is_url(url):
        return f'<a class="rlink" href="{ru.e(url)}">{ru.e(note.title or note.id)}</a>'
    return ru.resource(note.id) if ru.JIRA_KEY.search(note.id) else ru.e(note.title or note.id)


# ---- sections --------------------------------------------------------------------------------------
def _sec_understanding(understanding, pack, keys) -> str:
    tickets = " ".join(ru.jira_link(k) for k in keys) or "&mdash;"
    body = ru.md(understanding) if understanding else (
        "<p class='muted'>No understanding synthesised yet — run <code>refine</code> first.</p>")
    dl = (ru.download("pack summary", f"{pack.context_id}-pack.md", pack.summary_text())
          if pack.grounded else "")
    return (
        '<p class="lead">What the agent now understands is under test — the ticket and its synthesised '
        'understanding. Review it before approving the pack.</p>'
        f'<div class="box">{body}</div>'
        '<div class="kv">'
        f'<div><span class="k">Ticket(s)</span><span class="v">{tickets}</span></div>'
        f'<div><span class="k">Seed</span><span class="v">{ru.e(pack.seed or "&mdash;")}</span></div>'
        f'<div><span class="k">Sources gathered</span><span class="v">{len(pack.grounded)}</span></div>'
        f'<div><span class="k">Declared gaps</span><span class="v">{len(pack.gaps)}</span></div>'
        '</div>'
        + (f'<div class="dlrow">{dl}</div>' if dl else ""))


def _sec_map(pack) -> str:
    grounded = pack.grounded
    if not grounded:
        return "<p class='muted'>Nothing gathered yet — the knowledge map is empty.</p>"
    shown = grounded[:15]
    ids = {n.id: f"N{i}" for i, n in enumerate(shown)}
    lines = ["flowchart LR", "  SEED([" + ru.mlabel(pack.seed or pack.context_id) + "])"]
    # group nodes by kind into subgraphs, hub-linked from the seed
    by_kind: dict = defaultdict(list)
    for n in shown:
        by_kind[_kind(n)[1]].append(n)
    for gi, (label, notes) in enumerate(by_kind.items()):
        lines.append(f"  subgraph G{gi} [{ru.mlabel(label)}]")
        for n in notes:
            lines.append(f"    {ids[n.id]}[{ru.mlabel(n.title or n.id)}]")
        lines.append("  end")
        lines.append(f"  SEED --> G{gi}")
    # add resolvable edges (both ends are shown nodes — e.g. insight -> its source)
    for n in shown:
        for lr in n.links:
            tgt = ids.get(lr.target if hasattr(lr, "target") else "")
            if lr.in_scope and tgt and tgt != ids[n.id]:
                lines.append(f"  {ids[n.id]} --> {tgt}")
    trunc = (f'<p class="muted">Showing 15 of {len(grounded)} gathered nodes.</p>'
             if len(grounded) > 15 else "")
    return ('<p class="lead">The knowledge the agent gathered, grouped by source kind. Each node is one '
            'fetched source the understanding is built on.</p>' + ru.mermaid("\n".join(lines)) + trunc)


def _sec_concepts(pack) -> str:
    """The domain concepts the pack surfaced — each distilled note explained, with a diagram of its links."""
    concepts = [n for n in pack.grounded if n.synopsis][:6]
    if not concepts:
        return ("<p class='muted'>No distilled concepts yet — sources gathered but not summarised. "
                "Run <code>refine</code> to distill them.</p>")
    out = [('<p class="lead">The hard concepts and domain facts the agent extracted, in plain language — '
            'each with the sources it draws on.</p>')]
    for n in concepts:
        spokes = [lr for lr in n.links if lr.in_scope][:4]
        diagram = ""
        if spokes:
            lines = ["flowchart LR", f"  C[{ru.mlabel(n.title or n.id)}]"]
            for si, lr in enumerate(spokes):
                lbl = lr.anchor_text or lr.type or "link"
                lines.append(f"  C --> S{si}[{ru.mlabel(lbl)}]")
            diagram = ru.mermaid("\n".join(lines))
        out.append(
            f'<div class="dcard"><div class="d-head">{_chip(n)}'
            f'<span class="d-stmt">{ru.e(n.title or n.id)}</span></div>'
            f'<div class="d-why">{ru.e(n.synopsis)}</div>{diagram}</div>')
    return "\n".join(out)


def _sec_gaps(pack, open_q) -> str:
    if not pack.gaps and not open_q:
        return ("<p class='muted'>No open gaps or questions — the agent reached a confident "
                "understanding. Still worth a skim before approving.</p>")
    out = [('<p class="lead">What is missing, unreachable, or unresolved. Weigh these before you approve — '
            'each is a place the pack may be thin.</p>')]
    if open_q:
        out.append("<h3>Open questions</h3><div class='gaps'>")
        for q in open_q:
            why = f'<div class="d-why">{ru.e(q.why)}</div>' if q.why else ""
            rec = (f'<div class="d-chosen"><b>Suggested:</b> {ru.e(q.recommendation)}</div>'
                   if q.recommendation else "")
            out.append(f'<div class="gapcard"><div class="d-stmt">{ru.e(q.question)}</div>{why}{rec}</div>')
        out.append("</div>")
        out.append(ru.mermaid("flowchart LR\n  USER{{Approve?}}\n" + "\n".join(
            f'  Q{i}[{ru.mlabel(q.question)}] --> USER' for i, q in enumerate(open_q[:6]))))
    if pack.gaps:
        out.append("<h3>Declared gaps (unreachable / broken sources)</h3>")
        out.append("<ul class='tight'>" + "".join(f"<li>{ru.e(g)}</li>" for g in pack.gaps) + "</ul>")
    return "\n".join(out)


def _sec_sources(pack) -> str:
    grounded = pack.grounded
    if not grounded:
        return "<p class='muted'>No sources recorded for this run.</p>"
    by_kind: dict = defaultdict(list)
    for n in grounded:
        by_kind[_kind(n)[1]].append(n)
    out = [('<p class="lead">Every source the pack was built on — click through to the original. Grouped '
            'by kind.</p>')]
    for label, notes in by_kind.items():
        rows = "".join(
            f'<tr><td>{_note_link(n)}</td><td class="cell-desc">{ru.e(n.synopsis or "&mdash;")}</td></tr>'
            for n in notes)
        table = (f'<div class="tblwrap"><table><thead><tr><th>Source</th><th>What it contributes</th>'
                 f"</tr></thead><tbody>{rows}</tbody></table></div>")
        out.append(ru.details(f"{ru.e(label)} ({len(notes)})", table))
    return "\n".join(out)


def _sec_quality(bench) -> str:
    pqs = getattr(bench, "pqs", None) if bench else None
    parts = [('<p class="lead">Pack Quality Score from the Test-Evaluation agent (read-only). PQS is 0&ndash;1, '
              'weighted from the components below — a signal, not a gate.</p>'),
             (f'<div class="bmrow"><div class="score {ru.grade(pqs)}"><div class="n">{ru.fmt(pqs)}</div>'
              '<div class="l">PQS — pack quality</div></div></div>')]
    if bench is None:
        parts.append('<p class="muted">Not yet scored — run <code>evaluate_pack</code>. The rubric and '
                     'weights below still apply.</p>')
    comps = getattr(bench, "pqs_components", {}) if bench else {}
    rows = []
    for key, (label, weight, desc) in ru.PQS_META.items():
        val = comps.get(key) if comps else None
        contrib = f"{weight * float(val):.3f}" if isinstance(val, (int, float)) else "&mdash;"
        rows.append(f'<tr><td><b>{ru.e(label)}</b></td><td class="mono">{weight:.2f}</td>'
                    f'<td class="mono {ru.grade(val)}">{ru.fmt(val)}</td><td class="mono">{contrib}</td>'
                    f'<td class="cell-desc">{ru.e(desc)}</td></tr>')
    parts.append('<div class="tblwrap"><table><thead><tr><th>Component</th><th>Weight</th><th>Score</th>'
                 f'<th>Contribution</th><th>What it measures</th></tr></thead><tbody>{"".join(rows)}'
                 "</tbody></table></div>")
    if bench is not None and getattr(bench, "retrieval", None):
        r = bench.retrieval or {}
        parts.append("<h3>Retrieval highlights</h3><div class='tblwrap'><table><tbody>"
                     f"<tr><td>precision</td><td class='mono'>{ru.fmt(r.get('precision'))}</td></tr>"
                     f"<tr><td>recall</td><td class='mono'>{ru.fmt(r.get('recall'))}</td></tr>"
                     f"<tr><td>leaked (hard-neg)</td><td class='mono'>{ru.e(r.get('leaked'))}</td></tr>"
                     "</tbody></table></div>")
    return "\n".join(parts)


# ---- assembly --------------------------------------------------------------------------------------
def build_knowledge_report_html(bank, context_id: str) -> str:
    """Render the 6-section knowledge-preview report for `context_id` from the persisted pack."""
    pack = load_pack(bank, context_id)
    understanding = bank.read_understanding(context_id)
    questions = bank.read_questions(context_id)
    open_q = [q for q in questions if getattr(q, "status", "") == "open"]
    try:
        from common.benchmark.store import read_benchmark
        bench = read_benchmark(bank, context_id)
    except Exception:  # noqa: BLE001 — benchmark is optional; never fail the report on it
        bench = None

    keys = ru.all_jira_keys([context_id, pack.seed], [n.id for n in pack.grounded])
    bodies = {
        "k-understanding": _sec_understanding(understanding, pack, keys),
        "k-map": _sec_map(pack),
        "k-concepts": _sec_concepts(pack),
        "k-gaps": _sec_gaps(pack, open_q),
        "k-sources": _sec_sources(pack),
        "k-quality": _sec_quality(bench),
    }
    nav, secs = ru.nav_and_sections(_SECTIONS, bodies)
    ticket = keys[0] if keys else context_id
    header = (
        '<header><div class="eyebrow">Testing Agent &middot; Knowledge Preview</div>'
        f'<h1>Knowledge preview &mdash; {ru.e(ticket)}</h1>'
        f'<div class="meta"><span><b>Context</b> <span class="mono">{ru.e(context_id)}</span></span>'
        f'<span><b>Sources</b> {len(pack.grounded)}</span>'
        f'<span><b>Open questions</b> {len(open_q)}</span></div>'
        '<p class="lead">A preview of the gathered knowledge for you to review <b>before approving</b> '
        'the pack.</p></header>')
    footer = (f"Testing Agent knowledge preview &middot; context {ru.e(context_id)} &middot; "
              "deterministically rendered from the persisted pack (optional step, after refine / before approve).")
    return ru.page(f"Knowledge Preview - {ticket}", header, nav, secs, footer)
