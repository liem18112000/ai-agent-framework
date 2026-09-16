"""Self-contained, theme-aware HTML visualisation of the memory graph (memory_node + memory_edge).

A force-directed node-link page in the spirit of graphify's graph view: nodes coloured by `type`,
edges as links, drag + hover-for-synopsis. Zero dependencies — the whole force sim + canvas renderer
is inlined vanilla JS, so the page satisfies the Artifact CSP (no CDN / D3) and opens straight in a
browser. Pure render: `build_memory_graph_html(nodes, edges)` takes already-read rows and returns one
HTML string (no DB / bank access here — that lives in `memory_graph.py`)."""

from __future__ import annotations

import html as _html
import json

# Accessible, theme-neutral categorical palette (cycled by sorted node type). Distinct hues so a dozen
# node kinds stay separable in both light and dark.
_PALETTE = [
    "#2563eb", "#dc2626", "#059669", "#d97706", "#7c3aed", "#0891b2",
    "#db2777", "#65a30d", "#ea580c", "#4f46e5", "#0d9488", "#be123c",
]
_LINK_TARGET_TYPE = "(link target)"  # phantom node for an edge target absent from memory_node
_LINK_TARGET_COLOR = "#94a3b8"


def _colors(types: list[str]) -> dict[str, str]:
    """Deterministic type→hex colour: sorted types cycle the palette; phantom targets are muted grey."""
    palette = {t: _PALETTE[i % len(_PALETTE)] for i, t in enumerate(sorted(types))}
    palette[_LINK_TARGET_TYPE] = _LINK_TARGET_COLOR
    return palette


def build_memory_graph_html(nodes: list[dict], edges: list[dict], *, title: str = "Memory graph",
                            source: str = "", node_cap: int = 600) -> str:
    """Render `nodes` ({id,type,title,synopsis}) + `edges` ({source_id,target}) into a force-directed
    HTML page. Edge targets not present in `nodes` become muted phantom nodes so link structure shows.
    Capped at `node_cap` nodes (the overflow is stated on the page, never silently dropped)."""
    by_id = {n["id"]: n for n in nodes}
    total = len(by_id)
    kept = dict(list(by_id.items())[:node_cap])
    truncated = total - len(kept)

    # keep edges whose source survived; materialise missing targets as phantom "(link target)" nodes
    view_edges: list[dict] = []
    for e in edges:
        s, t = e.get("source_id"), e.get("target")
        if s not in kept or not t:
            continue
        if t not in kept:
            if len(kept) >= node_cap + node_cap:  # bound phantom growth too
                continue
            kept[t] = {"id": t, "type": _LINK_TARGET_TYPE, "title": t, "synopsis": ""}
        view_edges.append({"s": s, "t": t})

    types = sorted({n.get("type") or "?" for n in kept.values()})
    colors = _colors(types)
    d_nodes = [{"id": nid, "label": (n.get("title") or nid)[:60], "type": n.get("type") or "?",
                "color": colors.get(n.get("type") or "?", _PALETTE[0]),
                "syn": (n.get("synopsis") or "")[:280]} for nid, n in kept.items()]
    data = json.dumps({"nodes": d_nodes, "edges": view_edges}).replace("</", "<\\/")  # safe <script> embed

    legend = "".join(
        f'<span class="lg"><i style="background:{colors[t]}"></i>{_html.escape(t)}</span>' for t in types)
    meta = (f"{len(d_nodes)} nodes &middot; {len(view_edges)} edges"
            + (f" &middot; source: {_html.escape(source)}" if source else "")
            + (f' &middot; <b>capped</b> at {node_cap} of {total}' if truncated > 0 else ""))
    page = _SHELL
    for tok, val in (("__TITLE__", _html.escape(title)), ("__META__", meta),
                     ("__LEGEND__", legend), ("__CSS__", _CSS), ("__DATA__", data)):
        page = page.replace(tok, val)  # __DATA__ last so injected JSON is never re-scanned
    return page


_CSS = """
:root{--bg:#f8fafc;--fg:#0f172a;--muted:#64748b;--card:#ffffff;--line:#e2e8f0;--tip:#0f172a;--tipfg:#f8fafc}
@media (prefers-color-scheme:dark){:root{--bg:#0b1120;--fg:#e2e8f0;--muted:#94a3b8;--card:#111827;--line:#1f2937;--tip:#e2e8f0;--tipfg:#0b1120}}
:root[data-theme=dark]{--bg:#0b1120;--fg:#e2e8f0;--muted:#94a3b8;--card:#111827;--line:#1f2937;--tip:#e2e8f0;--tipfg:#0b1120}
:root[data-theme=light]{--bg:#f8fafc;--fg:#0f172a;--muted:#64748b;--card:#ffffff;--line:#e2e8f0;--tip:#0f172a;--tipfg:#f8fafc}
*{box-sizing:border-box}html,body{margin:0;height:100%}
body{background:var(--bg);color:var(--fg);font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;display:flex;flex-direction:column}
header{padding:12px 16px;border-bottom:1px solid var(--line);background:var(--card)}
h1{font-size:16px;margin:0 0 4px}.meta{color:var(--muted);font-size:12px}
.legend{margin-top:8px;display:flex;flex-wrap:wrap;gap:10px}
.lg{display:inline-flex;align-items:center;gap:5px;font-size:12px;color:var(--muted)}
.lg i{width:11px;height:11px;border-radius:3px;display:inline-block}
.stage{flex:1;position:relative;min-height:0}canvas{display:block;width:100%;height:100%;cursor:grab}
#tip{position:absolute;pointer-events:none;max-width:320px;padding:6px 9px;border-radius:6px;
  background:var(--tip);color:var(--tipfg);font-size:12px;opacity:0;transition:opacity .1s;z-index:2}
#tip b{display:block;margin-bottom:2px}
"""

_SHELL = """<title>__TITLE__</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>__CSS__</style>
<header>
  <h1>__TITLE__</h1>
  <div class="meta">__META__</div>
  <div class="legend">__LEGEND__</div>
</header>
<div class="stage"><canvas id="c"></canvas><div id="tip"></div></div>
<script>
const DATA=__DATA__;
const cv=document.getElementById('c'),ctx=cv.getContext('2d'),tip=document.getElementById('tip');
let W=0,H=0,DPR=Math.max(1,window.devicePixelRatio||1);
const idx=new Map(DATA.nodes.map((n,i)=>[n.id,i]));
const N=DATA.nodes.map(n=>({...n,x:0,y:0,vx:0,vy:0}));
const E=DATA.edges.map(e=>({s:idx.get(e.s),t:idx.get(e.t)})).filter(e=>e.s!=null&&e.t!=null);
function resize(){W=cv.clientWidth;H=cv.clientHeight;cv.width=W*DPR;cv.height=H*DPR;ctx.setTransform(DPR,0,0,DPR,0,0);}
window.addEventListener('resize',resize);resize();
// seed on a circle so the sim opens out instead of exploding from a point
N.forEach((n,i)=>{const a=i/N.length*6.283;n.x=W/2+Math.cos(a)*Math.min(W,H)*0.35;n.y=H/2+Math.sin(a)*Math.min(W,H)*0.35;});
// ponytail: O(n^2) repulsion per tick — fine to ~600 nodes (the render cap); swap for a quadtree if raised.
function tick(){
  const k=6000;                                   // repulsion strength
  for(let i=0;i<N.length;i++){let a=N[i];
    for(let j=i+1;j<N.length;j++){let b=N[j],dx=a.x-b.x,dy=a.y-b.y,d2=dx*dx+dy*dy||0.01,f=k/d2,
      d=Math.sqrt(d2),fx=dx/d*f,fy=dy/d*f;a.vx+=fx;a.vy+=fy;b.vx-=fx;b.vy-=fy;}}
  for(const e of E){let a=N[e.s],b=N[e.t],dx=b.x-a.x,dy=b.y-a.y,d=Math.sqrt(dx*dx+dy*dy)||1,f=(d-90)*0.02;
    a.vx+=dx/d*f;a.vy+=dy/d*f;b.vx-=dx/d*f;b.vy-=dy/d*f;}
  for(const n of N){n.vx+=(W/2-n.x)*0.001;n.vy+=(H/2-n.y)*0.001;      // gravity to centre
    if(n===drag)continue;n.x+=n.vx*=0.85;n.y+=n.vy*=0.85;}
}
function draw(){
  ctx.clearRect(0,0,W,H);
  ctx.strokeStyle=getComputedStyle(document.body).getPropertyValue('--line')||'#ccc';ctx.globalAlpha=0.7;
  ctx.beginPath();for(const e of E){ctx.moveTo(N[e.s].x,N[e.s].y);ctx.lineTo(N[e.t].x,N[e.t].y);}ctx.stroke();
  ctx.globalAlpha=1;ctx.font='11px sans-serif';
  for(const n of N){ctx.beginPath();ctx.fillStyle=n.color;ctx.arc(n.x,n.y,6,0,6.283);ctx.fill();
    ctx.fillStyle=getComputedStyle(document.body).getPropertyValue('--fg')||'#111';
    ctx.fillText(n.label,n.x+9,n.y+4);}
}
let frame=0;function loop(){if(frame++<600)tick();draw();requestAnimationFrame(loop);}loop();
// hover + drag
let drag=null;
function at(mx,my){for(let i=N.length-1;i>=0;i--){let n=N[i];if((n.x-mx)**2+(n.y-my)**2<100)return n;}return null;}
function pos(ev){const r=cv.getBoundingClientRect();return[ev.clientX-r.left,ev.clientY-r.top];}
cv.addEventListener('mousemove',ev=>{const[mx,my]=pos(ev);
  if(drag){drag.x=mx;drag.y=my;drag.vx=drag.vy=0;frame=Math.min(frame,300);return;}
  const n=at(mx,my);
  if(n){tip.innerHTML='<b>'+n.label+'</b>'+n.type+(n.syn?'<br>'+n.syn.replace(/</g,'&lt;'):'');
    tip.style.left=(mx+12)+'px';tip.style.top=(my+12)+'px';tip.style.opacity=1;cv.style.cursor='pointer';}
  else{tip.style.opacity=0;cv.style.cursor='grab';}});
cv.addEventListener('mousedown',ev=>{const[mx,my]=pos(ev);drag=at(mx,my);if(drag)cv.style.cursor='grabbing';});
window.addEventListener('mouseup',()=>{drag=null;});
</script>"""
