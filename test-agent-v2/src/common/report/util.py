"""Shared primitives for the self-contained HTML reports (test-plan + knowledge preview).

Generic render helpers + the ONE stylesheet + the mermaid loader + the page shell, so both reports read
as one system and neither re-implements escaping/markdown/links/diagrams. Lives in ``common`` and imports
no agent package. Diagrams use ``<pre class="mermaid">`` so they render in a browser (via the inlined
jsDelivr loader) and natively in the Artifact viewer; downloads are inline ``data:`` URLs (no server)."""

from __future__ import annotations

import html as _html
import os
import re
from urllib.parse import quote

JIRA_KEY = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
_MD_BOLD = re.compile(r"\*\*(.+?)\*\*")
_MD_CODE = re.compile(r"`([^`]+?)`")


# TEV rubric -- component -> (label, weight, what it measures). Weights mirror
# test_evaluation.metrics.{pqs,tps}.WEIGHTS; kept here so the rubric renders even before a run is scored.
PQS_META = {
    "faithfulness": ("Faithfulness", 0.30,
                     "Every claim in the knowledge pack is grounded in a retrieved source â no invented facts."),
    "ctx_precision": ("Context precision", 0.25,
                      "Share of the retrieved context that is actually relevant â signal vs. noise."),
    "ctx_recall": ("Context recall", 0.20,
                   "Share of the facts needed to test the ticket that the pack actually retrieved."),
    "relevancy": ("Answer relevancy", 0.15,
                  "How on-topic the retrieved context is to the ticket/requirement under test."),
    "trajectory": ("Retrieval trajectory", 0.10,
                   "Quality of the gather agent's tool/retrieval path (ADK trajectory)."),
}
TPS_META = {
    "fault_detection": ("Fault detection", 0.30,
                        "Estimated power of the suite to catch real defects â oracle/mutation-informed."),
    "brief_groundedness": ("Brief groundedness", 0.25,
                           "How tightly scenarios trace to the confirmed brief & ACs â no invented scope."),
    "coverage": ("Coverage", 0.20,
                 "Requirement Ã test-kind completeness, read from the coverage matrix (Â§6)."),
    "oracle_strength": ("Oracle strength", 0.15,
                        "Steps assert specific expected outcomes (a strong Then), not smoke checks."),
    "trajectory": ("Plan trajectory", 0.10,
                   "Quality of the define â implement decision path (ADK trajectory)."),
}


def e(s) -> str:
    return _html.escape(str(s) if s is not None else "")


def grade(score) -> str:
    """0–1 score -> css class (good/warn/bad); unknown -> 'na'."""
    if score is None:
        return "na"
    try:
        v = float(score)
    except (TypeError, ValueError):
        return "na"
    return "good" if v >= 0.8 else ("warn" if v >= 0.5 else "bad")


def fmt(score) -> str:
    if score is None:
        return "&mdash;"
    try:
        return f"{float(score):.2f}"
    except (TypeError, ValueError):
        return e(score)


def download(label: str, filename: str, content: str, mime: str = "application/json") -> str:
    """A self-contained download link (data: URL) — no server, works offline and in the Artifact viewer."""
    href = f"data:{mime};charset=utf-8,{quote(content)}"
    return f'<a class="dl" download="{e(filename)}" href="{href}">&#x2193;&nbsp;{e(label)}</a>'


def is_url(s) -> bool:
    return isinstance(s, str) and s.startswith(("http://", "https://"))


def jira_base() -> str:
    return (os.environ.get("ATLASSIAN_BASE_URL") or "").rstrip("/")


def jira_link(key: str) -> str:
    base = jira_base()
    return (f'<a class="rlink" href="{base}/browse/{e(key)}">{e(key)}</a>' if base
            else f'<span class="mono">{e(key)}</span>')


def resource(ref: str) -> str:
    """Render one source ref as a clickable/downloadable resource (URL, jira key, or opaque node id)."""
    if is_url(ref):
        return f'<a class="rlink" href="{e(ref)}">{e(ref)}</a>'
    m = JIRA_KEY.search(ref or "")
    if m:
        return jira_link(m.group(0))
    return f"<code>{e(ref)}</code>"


def all_jira_keys(*refs_lists) -> list[str]:
    keys: list[str] = []
    for refs in refs_lists:
        for r in refs or []:
            for m in JIRA_KEY.finditer(str(r)):
                if m.group(0) not in keys:
                    keys.append(m.group(0))
    return keys


# ---- minimal markdown (headings / lists / tables / inline) — no dependency ---------------------------
def md_inline(text: str) -> str:
    out = e(text)
    out = _MD_BOLD.sub(r"<b>\1</b>", out)
    return _MD_CODE.sub(r"<code>\1</code>", out)


def md(text: str | None) -> str:
    """Tiny markdown -> HTML for the persisted briefs/understanding (headings, bullets, tables, code)."""
    if not text:
        return ""
    lines = text.replace("\r\n", "\n").split("\n")
    html: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        st = lines[i].strip()
        if not st:
            i += 1
            continue
        if st.startswith("```"):                                   # fenced code
            buf = []
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            html.append(f'<pre class="code"><code>{e(chr(10).join(buf))}</code></pre>')
            continue
        if st.startswith("#"):                                     # heading (## -> h4, ### -> h5)
            lvl = len(st) - len(st.lstrip("#"))
            tag = {1: "h3", 2: "h4"}.get(lvl, "h5")
            html.append(f"<{tag}>{md_inline(st.lstrip('#').strip())}</{tag}>")
            i += 1
            continue
        if st.startswith("|") and i + 1 < n and set(lines[i + 1].strip()) <= set("|-: "):  # table
            head = [c.strip() for c in st.strip("|").split("|")]
            i += 2
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            th = "".join(f"<th>{md_inline(c)}</th>" for c in head)
            trs = "".join("<tr>" + "".join(f"<td>{md_inline(c)}</td>" for c in r) + "</tr>" for r in rows)
            html.append(f'<div class="tblwrap"><table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table></div>')
            continue
        if st[0] in "-*" and st[1:2] == " ":                       # bullet list
            items = []
            while i < n and lines[i].strip()[:2] in ("- ", "* "):
                items.append(f"<li>{md_inline(lines[i].strip()[2:])}</li>")
                i += 1
            html.append(f"<ul class='tight'>{''.join(items)}</ul>")
            continue
        para = [st]                                                # paragraph (until blank)
        i += 1
        while i < n and lines[i].strip() and lines[i].strip()[0] not in "#|-*`":
            para.append(lines[i].strip())
            i += 1
        html.append(f"<p>{md_inline(' '.join(para))}</p>")
    return "\n".join(html)


# ---- mermaid ---------------------------------------------------------------------------------------
def mlabel(text: str, limit: int = 66) -> str:
    """A mermaid-safe quoted label."""
    s = re.sub(r"\s+", " ", str(text or "").strip())
    s = re.sub(r'["\[\]{}()|<>#;`]', "", s)
    if len(s) > limit:
        s = s[: limit - 1].rstrip() + "…"
    return f'"{s}"'


def mermaid(code: str) -> str:
    return f'<pre class="mermaid">{e(code)}</pre>'


# ---- page shell (numbered sticky-nav sections + mermaid loader) -------------------------------------
def nav_and_sections(sections: list[tuple[str, str]], bodies: dict[str, str]) -> tuple[str, str]:
    """(nav, sections) HTML from ``[(id, label)]`` + ``{id: body_html}`` — numbered 1..N."""
    nav = "".join(f'<a href="#{sid}"><span class="num">{i}</span>{e(label)}</a>'
                  for i, (sid, label) in enumerate(sections, 1))
    secs = "".join(
        f'<section id="{sid}"><h2><span class="secnum">{i}</span>{e(label)}</h2>{bodies[sid]}</section>'
        for i, (sid, label) in enumerate(sections, 1))
    return nav, secs


def page(title: str, header: str, nav: str, secs: str, footer: str) -> str:
    """One self-contained HTML page: title + shared CSS + header + sticky nav + sections + mermaid loader."""
    return f"""<title>{e(title)}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>{CSS}</style>
<div class="wrap">
  {header}
  <nav class="toc">{nav}</nav>
  {secs}
  <footer>{footer}</footer>
</div>
<script type="module">
try {{
  const m = await import('https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs');
  m.default.initialize({{startOnLoad:true, securityLevel:'strict',
    theme: matchMedia('(prefers-color-scheme:dark)').matches ? 'dark' : 'default'}});
}} catch (e) {{ /* offline / CSP (e.g. Artifact viewer): <pre class="mermaid"> renders natively or shows source */ }}
</script>"""


CSS = """
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
h1{font-size:29px;margin:.3em 0 .1em;letter-spacing:-.01em}
h2{font-size:20px;margin:1.6em 0 .5em;border-bottom:1px solid var(--line);padding-bottom:.3em;display:flex;align-items:center;gap:.5em;scroll-margin-top:64px}
h3{font-size:14px;color:var(--ink-2);margin:1.3em 0 .4em}h4{font-size:13px;color:var(--ink-2);margin:1em 0 .3em}h5{font-size:12.5px;color:var(--muted);margin:.8em 0 .3em}
p{margin:.5em 0}.muted{color:var(--muted)}.mono{font-family:var(--mono)}
.lead{color:var(--ink-2);font-size:14px;max-width:74ch}
.meta{display:flex;flex-wrap:wrap;gap:6px 20px;margin-top:12px;color:var(--ink-2);font-size:13px}.meta b{color:var(--ink)}
.secnum{font:700 13px var(--mono);color:#fff;background:var(--accent);border-radius:6px;padding:1px 9px;flex:0 0 auto}
section{scroll-margin-top:64px}
.toc{position:sticky;top:0;z-index:5;display:flex;flex-wrap:wrap;gap:4px;margin:20px 0 6px;padding:10px 0;background:var(--bg);border-bottom:1px solid var(--line)}
.toc a{display:inline-flex;align-items:center;gap:6px;font:600 12.5px var(--sans);color:var(--ink-2);text-decoration:none;border:1px solid transparent;border-radius:8px;padding:5px 10px}
.toc a:hover{background:var(--surface-2);color:var(--accent)}
.toc .num{font:700 10.5px var(--mono);color:var(--accent);background:var(--accent-soft);border-radius:5px;padding:1px 6px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:6px}@media(max-width:640px){.grid2{grid-template-columns:1fr}}
.box{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px 16px}.box h3{margin-top:0}
.kv{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin:14px 0}
.kv>div{background:var(--surface);border:1px solid var(--line);border-radius:9px;padding:9px 12px}
.kv .k{display:block;font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}
.kv .v{display:block;font-size:14px;font-weight:600;margin-top:2px}
.reslist{display:flex;flex-wrap:wrap;gap:8px}.res{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:5px 10px;font-size:12.5px}
.rlink{color:var(--accent);text-decoration:none;border-bottom:1px solid var(--accent-soft)}.rlink:hover{border-bottom-color:var(--accent)}
.scopelist{list-style:none;margin:.2em 0;padding:0}.scopelist li{position:relative;padding-left:1.4em;margin:.35em 0;font-size:13.5px;color:var(--ink-2)}
.scopelist li::before{position:absolute;left:0;font-weight:700}.scope-in li::before{content:"+";color:var(--scope-in)}.scope-out li::before{content:"\\2013";color:var(--scope-out)}
.chip{display:inline-flex;align-items:center;font-size:11px;font-weight:600;letter-spacing:.03em;text-transform:uppercase;padding:3px 9px;border-radius:999px;white-space:nowrap}
.chip.happy{color:var(--k-happy);background:var(--k-happy-bg)}.chip.negative{color:var(--k-negative);background:var(--k-negative-bg)}
.chip.boundary{color:var(--k-boundary);background:var(--k-boundary-bg)}.chip.error{color:var(--k-error);background:var(--k-error-bg)}
.chip.security{color:var(--k-security);background:var(--k-security-bg)}.chip.concurrency{color:var(--k-concurrency);background:var(--k-concurrency-bg)}
.chip.encoding{color:var(--k-encoding);background:var(--k-encoding-bg)}.chip.perf{color:var(--k-perf);background:var(--k-perf-bg)}
.chip.other{color:var(--k-other);background:var(--k-other-bg)}
.chip.jira{color:var(--k-boundary);background:var(--k-boundary-bg)}.chip.confluence{color:var(--k-concurrency);background:var(--k-concurrency-bg)}
.chip.code{color:var(--k-security);background:var(--k-security-bg)}.chip.insight{color:var(--k-happy);background:var(--k-happy-bg)}
.chip.web{color:var(--k-perf);background:var(--k-perf-bg)}.chip.attachment{color:var(--k-negative);background:var(--k-negative-bg)}
.dcard,.gapcard{background:var(--surface);border:1px solid var(--line);border-left:3px solid var(--accent);border-radius:9px;padding:11px 14px;margin:9px 0}
.gapcard{border-left-color:var(--warn)}
.d-head{display:flex;align-items:baseline;gap:9px;flex-wrap:wrap}.d-stmt{font-size:14px;font-weight:600}
.d-chosen{font-size:13.5px;color:var(--ink-2);margin:.35em 0}.d-why{font-size:13px;color:var(--muted);margin:.25em 0}
.d-rej{font-size:12.5px;color:var(--bad);margin:.25em 0}.d-prov{font-size:12px;color:var(--muted);margin-top:.35em}
.pill{display:inline-block;font-size:11px;font-weight:700;text-transform:uppercase;padding:2px 9px;border-radius:999px;color:var(--good);background:var(--k-happy-bg)}
.pill.low,.pill.medium{color:var(--warn);background:var(--k-negative-bg)}
.oracle{margin-top:8px;padding-top:8px;border-top:1px dashed var(--line);font-size:13px;color:var(--ink-2)}
.oracle .tag{font:700 10.5px var(--mono);letter-spacing:.09em;text-transform:uppercase;color:var(--accent);margin-right:.5em}
.code,.gherkin{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px;overflow-x:auto;font:12.5px/1.5 var(--mono);color:var(--ink-2)}
table{width:100%;border-collapse:collapse;font-size:13.5px}.tblwrap{overflow-x:auto;margin:.4em 0}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);vertical-align:top}th{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
td.mono{font-family:var(--mono);font-size:12.5px}.cell-desc{color:var(--ink-2);font-size:12.5px}
td.mono.good{color:var(--good)}td.mono.warn{color:var(--warn)}td.mono.bad{color:var(--bad)}
td.cov{text-align:center;font-weight:700}td.cov.y{color:var(--good)}td.cov.n{color:var(--muted)}
.bmrow{display:flex;flex-wrap:wrap;gap:14px;margin:10px 0}
.score{background:var(--surface);border:1px solid var(--line);border-left:4px solid var(--muted);border-radius:10px;padding:12px 18px;min-width:130px}
.score.good{border-left-color:var(--good)}.score.bad{border-left-color:var(--bad)}.score.warn{border-left-color:var(--warn)}
.score .n{font-size:30px;font-weight:700;font-variant-numeric:tabular-nums}.score.good .n{color:var(--good)}.score.bad .n{color:var(--bad)}.score.warn .n{color:var(--warn)}
.score .l{font-size:11px;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);margin-top:3px}
ul.tight,ol.tight{margin:.3em 0;padding-left:1.3em}ul.tight li,ol.tight li{margin:.28em 0;font-size:13.5px;color:var(--ink-2)}
.wf{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:12px 0}
.wf-head{display:flex;align-items:center;gap:9px;flex-wrap:wrap}.wf-n{font:700 12px var(--mono);color:#fff;background:var(--accent);border-radius:6px;padding:1px 7px}
.wf-title{font-size:14.5px;font-weight:650}.wf-why{font-size:13px;color:var(--ink-2);margin:.5em 0 .7em}
.fl{display:flex;flex-direction:column;gap:0}.fl-step{display:flex;gap:10px;padding:7px 0;position:relative}
.fl-step:not(:last-child)::after{content:"";position:absolute;left:52px;top:26px;bottom:-3px;width:2px;background:var(--line)}
.fl-kw{flex:0 0 auto;align-self:flex-start;font:700 10.5px var(--mono);text-transform:uppercase;letter-spacing:.06em;color:var(--accent);background:var(--accent-soft);border:1px solid var(--line);border-radius:6px;padding:3px 8px;min-width:74px;text-align:center}
.fl-body{flex:1 1 auto}.fl-act{font-size:13.5px;color:var(--ink)}.fl-exp{font-size:12.5px;color:var(--muted);margin-top:2px}.fl-data{font-size:12px;color:var(--ink-2);margin-top:2px}
.dlrow{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}
.dl{display:inline-flex;align-items:center;font:600 12px var(--sans);color:var(--accent);background:var(--accent-soft);border:1px solid var(--line);border-radius:8px;padding:5px 11px;text-decoration:none}
.dl:hover{background:var(--surface-2)}
.mermaid{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:16px;margin:.6em 0;overflow-x:auto;font-family:var(--mono);font-size:12px;color:var(--ink-2)}
footer{margin-top:48px;padding-top:16px;border-top:1px solid var(--line);color:var(--muted);font-size:12px}
@media print{.toc{position:static}section{break-inside:avoid}}
"""
