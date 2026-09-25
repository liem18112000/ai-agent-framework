"""Q5 — the codegraph-driven coverage matrix.

The denominator of "100% coverage" is a set of **logic units**:
  - REQUIREMENT units — every grounded note (acceptance criterion / behaviour) + every insight.
  - CODE units — the codegraph's inbound **endpoints** and core **hub** abstractions (graphify is
    symbol-level, so these are the practical proxy for "branches"; there are no branch nodes).

For each requirement unit we compute which of the plan's OPEN kinds a generated scenario covers
(traceability via `source_refs`), and a **gap report** of the (unit × kind) cells still empty.

R2 adds the other direction. Everything above measures RECALL — "what is missing?". The drift
fields measure PRECISION — "does this scenario serve anything?": `orphan_scenarios` (cites no
resolvable requirement unit) and `out_of_scope_hits` (names something the plan ruled OUT). A
scenario citing nothing was previously absent from `covered` and reported by NOTHING.

Code units are marked *reached* when a covering scenario or a covered requirement note names them — a
STRUCTURAL, design-time signal, honestly labelled: true executed/branch coverage needs the Test
Executor agent (RESEARCH-test-executor-agent.md). When no codegraph exists the matrix degrades to
requirement-only and says so.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass, field

from common.codegraph.store import read_registry
from common.models import CODEGRAPH
from common.testplan.models import DEFAULT_KINDS as _DEFAULT_KINDS
from common.testplan.models import effective_kinds

_WORD = re.compile(r"[a-z0-9]+")


@dataclass
class CoverageUnit:
    """One unit of logic in the denominator."""

    id: str
    category: str  # "requirement" | "endpoint" | "hub"
    title: str
    source_file: str = ""


@dataclass
class CoverageMatrix:
    context_id: str
    kinds: list[str] = field(default_factory=list)
    units: list[CoverageUnit] = field(default_factory=list)
    covered: dict[str, list[str]] = field(default_factory=dict)  # requirement unit id -> kinds covered
    reached_code: list[str] = field(default_factory=list)        # code unit ids a scenario/AC names
    gaps: list[dict] = field(default_factory=list)               # {id, title, category, missing}
    requirement_cells: int = 0
    requirement_cells_covered: int = 0
    code_units: int = 0
    code_units_reached: int = 0
    has_codegraph: bool = False
    # R2 — the DRIFT half. Every field above answers "what is MISSING?" (recall). These two answer
    # "does this scenario serve anything?" (precision) — a scenario citing nothing resolvable is
    # silently absent from `covered` and was never reported anywhere.
    scenarios_total: int = 0
    orphan_scenarios: list[dict] = field(default_factory=list)    # {id, title, cause}
    out_of_scope_hits: list[dict] = field(default_factory=list)   # {id, title, matched, cause}

    @property
    def drift_count(self) -> int:
        """Scenarios implicated in drift (an orphan that also names an out-of-scope item counts once)."""
        return len({s["id"] for s in (*self.orphan_scenarios, *self.out_of_scope_hits)})

    @property
    def drift_causes(self) -> dict[str, int]:
        """R7 — findings per disposition, e.g. {"JUDGMENT-GAP": 3}. Zero-valued causes are omitted.
        THIS is the calibration signal: a run dominated by CONTEXT-GAP says invest in gather, one
        dominated by JUDGMENT-GAP says invest in the generation prompt."""
        return dict(Counter(
            c for s in (*self.orphan_scenarios, *self.out_of_scope_hits) if (c := s.get("cause"))))

    @property
    def requirement_pct(self) -> float:
        return round(100 * self.requirement_cells_covered / self.requirement_cells, 1) \
            if self.requirement_cells else 0.0

    @property
    def code_pct(self) -> float:
        return round(100 * self.code_units_reached / self.code_units, 1) if self.code_units else 0.0


def _tokens(*texts: str) -> set[str]:
    return {t for text in texts for t in _WORD.findall((text or "").lower()) if len(t) > 2}


def _requirement_units(pack) -> list[CoverageUnit]:
    units = [CoverageUnit(id=n.id, category="requirement", title=n.title or n.id)
             for n in pack.grounded if n.type != CODEGRAPH]
    units += [CoverageUnit(id=i.id, category="requirement", title=(i.statement or i.id)[:80])
              for i in pack.insights]
    return units


#: Share of an out-of-scope phrase's tokens a scenario must name before it counts as a hit.
# ponytail: token overlap, no semantics — it cannot tell "we do NOT test QR" from "test QR". Tuned
# conservative: a noisy drift number gets ignored, which is worse than a quiet one. Two known blind
# spots, both deliberate — a phrase of only ≤2-char tokens ("QR") yields no tokens and can never
# match, and a one-word overlap never fires (so out_of_scope "performance testing" does not flag
# "Login performance under load"). Upgrade path is the JEV judge over the residue, once these
# counters are actually being read — see §8 of docs/RESEARCH-openrig-intent-hierarchy.md.
_OOS_MIN_OVERLAP = 0.6


#: R7 — openrig's miss DISPOSITION, one word per finding. CONTEXT-GAP: the pack lacked what the
#: moment needed, so the fix lands upstream in gather. JUDGMENT-GAP: the context WAS there and the
#: call was still wrong, so the fix is a check on generation. The value of any single word is small;
#: the RATE across runs is the calibration — it says whether to invest in the pack or in the prompt.
CONTEXT_GAP = "CONTEXT-GAP"
JUDGMENT_GAP = "JUDGMENT-GAP"


def _orphan_scenarios(scenarios, req_units) -> list[dict]:
    """Scenarios citing no resolvable requirement unit — cite nothing, or cite a dangling ref.

    R7 disposes each by CAUSE. With an empty pack there was nothing to cite, so the miss belongs
    upstream (CONTEXT-GAP → fix gather). With units present the generator had them and still cited
    none, so the miss is its own (JUDGMENT-GAP → fix the prompt / add a check)."""
    unit_ids = {u.id for u in req_units}
    cause = CONTEXT_GAP if not unit_ids else JUDGMENT_GAP
    return [{"id": sc.id, "title": sc.title, "cause": cause} for sc in scenarios or []
            if not (set(sc.source_refs) & unit_ids)]


def _is_node_id(entry: str) -> bool:
    """`jira:LUZ-1` / `codegraph:ws/repo` — an id, not prose. Prose phrases carry whitespace."""
    return ":" in entry and " " not in entry


def _out_of_scope_hits(plan, scenarios) -> list[dict]:
    """Scenarios reaching for something the plan puts OUT of scope.

    `plan.out_of_scope` takes TWO real shapes in this pipeline, so both are matched:

    - **pack NODE IDS** — the assured loop overwrites the field with ``grounded_ids - in_scope_ids``
      from the scope classifier and PERSISTS it (``assured/loop.py``), so this is what coverage sees
      on any run where the classifier fired, i.e. the normal production shape. Matched EXACTLY
      against the scenario's ``source_refs`` — no tokens, no threshold, no blind spots.
    - **define's PROSE** ("QR code fallback removal") — what survives when the classifier did not run
      (no model configured). Matched on token overlap, with the ceilings noted at `_OOS_MIN_OVERLAP`.
    """
    entries = [p for p in ((plan.out_of_scope if plan else None) or []) if p]
    ids = {p for p in entries if _is_node_id(p)}
    phrases = [(p, toks) for p in entries if p not in ids and (toks := _tokens(p))]
    hits: list[dict] = []
    for sc in scenarios or []:
        # R7: always JUDGMENT-GAP. The boundary was stated AND fed to the generator (`_scope_block`),
        # so crossing it is a wrong call with the context present, never a missing-context miss.
        if named := sorted(set(sc.source_refs) & ids):        # exact: cites an out-of-scope node
            hits.append({"id": sc.id, "title": sc.title, "matched": named[0], "cause": JUDGMENT_GAP})
            continue
        text = _tokens(sc.title, sc.description)
        for phrase, ptoks in phrases:
            shared = ptoks & text
            if len(shared) >= min(2, len(ptoks)) and len(shared) / len(ptoks) >= _OOS_MIN_OVERLAP:
                hits.append({"id": sc.id, "title": sc.title, "matched": phrase, "cause": JUDGMENT_GAP})
                break  # one hit per scenario — the finding is "this drifted", not "how many ways"
    return hits


def _repos_in_pack(pack) -> set[str]:
    """The repo slugs referenced by the pack's codegraph notes (title = 'ws/repo')."""
    return {n.title.split("/")[-1] for n in pack.grounded
            if n.type == CODEGRAPH and n.title}


def _code_units(bank, pack) -> list[CoverageUnit]:
    repos = _repos_in_pack(pack)
    if not repos:
        return []
    units: list[CoverageUnit] = []
    for row in read_registry(bank):
        repo = row.get("repo", "")
        if repo not in repos:
            continue
        for ep in row.get("endpoints", []):
            base = ep.rsplit("/", 1)[-1]
            units.append(CoverageUnit(id=f"endpoint:{repo}:{base}", category="endpoint",
                                      title=base, source_file=ep))
        for g in row.get("god_nodes", []):
            name = g.get("name", "") if isinstance(g, dict) else str(g)
            if name:
                units.append(CoverageUnit(id=f"hub:{repo}:{name}", category="hub", title=name))
    return units


def build_coverage_matrix(bank, context_id: str, *, plan=None, pack=None,
                          scenarios=None) -> CoverageMatrix:
    """Assemble the coverage matrix for one context from its plan + pack + generated scenarios."""
    from common.testplan import memory as store
    from common.testplan.pack import load_plan_pack

    plan = plan if plan is not None else store.read_plan(bank, context_id)
    pack = pack if pack is not None else load_plan_pack(bank, context_id).pack
    scenarios = scenarios if scenarios is not None else store.read_scenarios(bank, context_id)

    kinds = effective_kinds(plan) if plan else list(_DEFAULT_KINDS)
    req_units = _requirement_units(pack)
    code_units = _code_units(bank, pack)
    m = CoverageMatrix(context_id=context_id, kinds=kinds, units=req_units + code_units,
                       has_codegraph=bool(code_units))

    # Requirement × kind traceability from each scenario's cited source_refs.
    covered_by_kind: dict[str, set[str]] = {u.id: set() for u in req_units}
    for sc in scenarios or []:
        for ref in sc.source_refs:
            if ref in covered_by_kind:
                covered_by_kind[ref].add(sc.kind)
    m.covered = {uid: sorted(ks) for uid, ks in covered_by_kind.items()}
    m.requirement_cells = len(req_units) * len(kinds)
    m.requirement_cells_covered = sum(len(covered_by_kind[u.id] & set(kinds)) for u in req_units)
    for u in req_units:
        if missing := [k for k in kinds if k not in covered_by_kind[u.id]]:
            m.gaps.append({"id": u.id, "title": u.title, "category": "requirement",
                           "missing": missing})

    # Code units: reached when a covering scenario or a covered requirement note names them.
    covered_note_titles = [u.title for u in req_units if covered_by_kind[u.id]]
    scenario_text = _tokens(*[f"{s.title} {s.description}" for s in scenarios or []],
                            *covered_note_titles)
    m.code_units = len(code_units)
    for cu in code_units:
        stem = cu.title.rsplit(".", 1)[0]
        if _tokens(stem) & scenario_text:
            m.reached_code.append(cu.id)
        else:
            m.gaps.append({"id": cu.id, "title": cu.title, "category": cu.category,
                           "missing": ["reach"]})
    m.code_units_reached = len(m.reached_code)

    # R2 — the drift half: which scenarios serve nothing, and which serve something ruled OUT.
    m.scenarios_total = len(scenarios or [])
    m.orphan_scenarios = _orphan_scenarios(scenarios, req_units)
    m.out_of_scope_hits = _out_of_scope_hits(plan, scenarios)
    return m


def render_coverage_md(m: CoverageMatrix) -> str:
    lines = [f"# Coverage matrix — {m.context_id}", "",
             f"Kinds (open taxonomy): {', '.join(m.kinds)}", "",
             (f"- **Requirement × kind cells:** {m.requirement_cells_covered}/{m.requirement_cells} "
              f"covered ({m.requirement_pct}%)")]
    if m.has_codegraph:
        lines.append(f"- **Code units (codegraph endpoints + hubs):** {m.code_units_reached}/"
                     f"{m.code_units} reached ({m.code_pct}%)")
    else:
        lines.append("- **Code units:** none — no codegraph for this context (requirement-only matrix)")
    lines += ["",
              ("> Design-time coverage. Executed/branch coverage + mutation need the Test Executor "
               "agent; this matrix measures what was *designed*, not what a run proved."),
              "", "## Traceability (requirement → kinds covered)"]
    req = [u for u in m.units if u.category == "requirement"]
    lines += [f"- `{u.id}` — {u.title}: {', '.join(m.covered.get(u.id) or []) or '(none)'}"
              for u in req] or ["- (no requirement units)"]
    if m.gaps:
        lines += ["", f"## Gaps ({len(m.gaps)}) — close toward 100%"]
        lines += [f"- [{g['category']}] `{g['id']}` — {g['title']}: missing "
                  f"{', '.join(g['missing'])}" for g in m.gaps]
    if m.orphan_scenarios or m.out_of_scope_hits:
        lines += ["", (f"## Drift ({m.drift_count} of {m.scenarios_total} scenarios) — "
                       "work that serves no stated intent")]
        if causes := m.drift_causes:
            lines += ["", "Disposition: " + ", ".join(f"{n} {c}" for c, n in sorted(causes.items()))
                      + " — CONTEXT-GAP means fix the pack (gather); JUDGMENT-GAP means fix the "
                        "generation prompt.", ""]
        lines += [f"- [orphan · {s.get('cause', '')}] `{s['id']}` — {s['title']}: "
                  "cites no requirement unit" for s in m.orphan_scenarios]
        lines += [f"- [out-of-scope · {s.get('cause', '')}] `{s['id']}` — {s['title']}: "
                  f"names \"{s['matched']}\"" for s in m.out_of_scope_hits]
    return "\n".join(lines) + "\n"


def coverage_summary(m: CoverageMatrix) -> str:
    """One-line summary for the implement reply."""
    code = f"; code units {m.code_units_reached}/{m.code_units} reached" if m.has_codegraph else \
        "; no codegraph"
    causes = "; ".join(f"{n} {c}" for c, n in sorted(m.drift_causes.items()))
    drift = (f" DRIFT: {len(m.orphan_scenarios)} orphan, {len(m.out_of_scope_hits)} out-of-scope "
             f"of {m.scenarios_total} scenario(s)"
             + (f" ({causes})." if causes else ".")) if m.drift_count else ""
    return (f"Coverage: {m.requirement_cells_covered}/{m.requirement_cells} AC×kind cells "
            f"({m.requirement_pct}%){code}; {len(m.gaps)} gap(s).{drift}")


def as_dict(m: CoverageMatrix) -> dict:
    d = asdict(m)
    d["units"] = [asdict(u) for u in m.units]
    d["drift_count"] = m.drift_count     # properties are invisible to asdict()
    d["drift_causes"] = m.drift_causes
    return d
