"""Q5 — the codegraph-driven coverage matrix.

The denominator of "100% coverage" is a set of **logic units**:
  - REQUIREMENT units — every grounded note (acceptance criterion / behaviour) + every insight.
  - CODE units — the codegraph's inbound **endpoints** and core **hub** abstractions (graphify is
    symbol-level, so these are the practical proxy for "branches"; there are no branch nodes).

For each requirement unit we compute which of the plan's OPEN kinds a generated scenario covers
(traceability via `source_refs`), and a **gap report** of the (unit × kind) cells still empty. Code
units are marked *reached* when a covering scenario or a covered requirement note names them — a
STRUCTURAL, design-time signal, honestly labelled: true executed/branch coverage needs the Test
Executor agent (RESEARCH-test-executor-agent.md). When no codegraph exists the matrix degrades to
requirement-only and says so.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from common.codegraph.store import read_registry
from common.models import CODEGRAPH

_DEFAULT_KINDS = ("happy", "negative", "boundary", "error")
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

    kinds = list(plan.test_kinds) if (plan and plan.test_kinds) else list(_DEFAULT_KINDS)
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
    return "\n".join(lines) + "\n"


def coverage_summary(m: CoverageMatrix) -> str:
    """One-line summary for the implement reply."""
    code = f"; code units {m.code_units_reached}/{m.code_units} reached" if m.has_codegraph else \
        "; no codegraph"
    return (f"Coverage: {m.requirement_cells_covered}/{m.requirement_cells} AC×kind cells "
            f"({m.requirement_pct}%){code}; {len(m.gaps)} gap(s).")


def as_dict(m: CoverageMatrix) -> dict:
    d = asdict(m)
    d["units"] = [asdict(u) for u in m.units]
    return d
