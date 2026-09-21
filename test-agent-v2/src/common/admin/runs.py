"""F1 — run history: enumerate past runs and render one run's full test detail (read-only)."""

from __future__ import annotations

import json
from dataclasses import dataclass

from common.admin._shared import (
    _REFINE_PREFIX,
    _RUNS_PREFIX,
    _kinds_str,
    _run_contexts,
    _slug,
    _store,
)
from common.interrogate.pack import load_pack
from common.learn.store import iter_lessons
from common.models import INSIGHT

_SECTION_CAP = 4000   # per free-text section — get_run is a summary; full bodies via the dedicated tools
_TOTAL_CAP = 24000    # hard backstop on the whole report so it never blows the MCP token limit


def _clip(text: str, hint: str, empty: str, cap: int = _SECTION_CAP) -> str:
    """A get_run section body, capped: full text if small, else a head + a pointer to the read tool
    that returns it in full. Keeps get_run a bounded summary instead of an unbounded dump."""
    text = (text or "").strip()
    if not text:
        return empty
    if len(text) <= cap:
        return text
    return f"{text[:cap]}\n\n… [truncated {len(text) - cap} more chars — full via `{hint}`]"


@dataclass
class RunSummary:
    context_id: str
    seed: str = ""
    started: str = ""
    ended: str = ""
    refine_done: bool = False
    questions: int = 0
    answered: int = 0
    pack_nodes: int = 0
    understanding: bool = False
    lessons: int = 0
    artifacts: int = 0

    def row(self) -> str:
        return (f"| {self.context_id} | {self.seed or '-'} | {self.started or '-'} | "
                f"{'yes' if self.refine_done else 'no'} | {self.answered}/{self.questions} | "
                f"{self.pack_nodes} | {'yes' if self.understanding else 'no'} | {self.lessons} | "
                f"{self.artifacts} |")


@dataclass
class RunDetail:
    context_id: str
    seed: str = ""
    started: str = ""
    refine_done: bool = False
    understanding: str = ""
    questions: list = None  # list[Question]
    answers: list = None  # list[Answer]
    pack_kinds: dict = None  # {type: count}
    pack_nodes: int = 0
    plan_brief: str = ""
    scenarios_md: str = ""
    coverage_md: str = ""
    run_logs: list = None  # list[str]
    lessons: list = None  # list[dict]
    artifacts: list = None  # list[dict] — recorded published-report URLs, newest first

    def md(self) -> str:
        qs, ans = self.questions or [], self.answers or []
        out = [f"# Run {self.context_id}", ""]
        out.append(f"- seed: {self.seed or '-'}")
        out.append(f"- started: {self.started or '-'}")
        out.append(f"- refine done: {'yes' if self.refine_done else 'no'}")
        out.append(f"- pack: {self.pack_nodes} nodes ({_kinds_str(self.pack_kinds or {})})")
        out.append("")
        out.append("## Understanding brief")
        out.append(_clip(self.understanding, "get_understanding", "_none yet_"))
        out.append("")
        by_ans = {a.question_id: a for a in ans}
        out.append(f"## Q&A ({len([q for q in qs if q.id in by_ans])}/{len(qs)} answered)")
        for q in qs:
            a = by_ans.get(q.id)
            out.append(f"- [{q.status}] ({q.round}) {q.question}")
            if a:
                out.append(f"    → {a.chosen_option or ''} {a.text}".rstrip())
        if not qs:
            out.append("_no questions_")
        out.append("")
        out.append("## Test plan")
        out.append(_clip(self.plan_brief, "get_plan", "_no plan yet_"))
        out.append("")
        out.append("## Scenarios")
        out.append(_clip(self.scenarios_md, "get_scenarios", "_no scenarios yet_"))
        out.append("")
        out.append("## Coverage matrix")
        out.append(_clip(self.coverage_md, "get_coverage", "_no coverage yet_"))
        out.append("")
        out.append("## Run logs")
        out.extend(f"- {r}" for r in (self.run_logs or ["_none_"]))
        out.append("")
        out.append(f"## Lessons captured ({len(self.lessons or [])})")
        out.extend(f"- [{lsn['kind']}] {lsn['statement']}" for lsn in (self.lessons or []))
        if not self.lessons:
            out.append("_none_")
        out.append("")
        out.append(f"## Artifacts ({len(self.artifacts or [])})")
        for a in (self.artifacts or []):
            title = f" — {a['title']}" if a.get("title") else ""
            out.append(f"- [{a.get('kind', '')}]{title} — {a.get('url', '')}")
        if not self.artifacts:
            out.append("_no artifacts recorded_")
        out.append("")
        out.append("_Eval scores are computed on demand via evaluate_pack / evaluate_plan; not stored._")
        report = "\n".join(out)
        if len(report) > _TOTAL_CAP:  # backstop: never exceed the MCP token limit regardless of section
            report = report[:_TOTAL_CAP] + f"\n\n… [get_run report capped at {_TOTAL_CAP} chars]"
        return report


def _pack_counts(bank) -> tuple[dict[str, int], dict[str, dict]]:
    """One index pass → {run_id: node_count}, {run_id: {type: count}} across all gathered notes.

    ponytail: reads every note sidecar once per call — fine for a rarely-run operator tool; add a
    projection only if list_runs gets slow."""
    graph, _ = bank.load_index()
    counts: dict[str, int] = {}
    kinds: dict[str, dict] = {}
    for node in graph.nodes.values():
        if node.get("type") == INSIGHT:
            continue
        note = bank.read_note(node["id"], node["type"])
        if note is None:
            continue
        counts[note.run_id] = counts.get(note.run_id, 0) + 1
        kinds.setdefault(note.run_id, {})[note.type] = kinds.setdefault(note.run_id, {}).get(note.type, 0) + 1
    return counts, kinds


def _lesson_counts(bank) -> dict[str, int]:
    counts: dict[str, int] = {}
    for ins in iter_lessons(bank):
        counts[ins.context_id] = counts.get(ins.context_id, 0) + 1
    return counts


def list_runs(bank, limit: int = 50) -> str:
    """Every past pipeline run, newest first (F1) — enumerated from memory/refine/*/ (no sidecar)."""
    packs, _ = _pack_counts(bank)
    lessons = _lesson_counts(bank)
    summaries: list[RunSummary] = []
    for ctx in _run_contexts(bank):
        state = bank.read_refine_state(ctx)
        qs = bank.read_questions(ctx)
        answers = bank.read_answers(ctx)
        summaries.append(RunSummary(
            context_id=ctx, seed=state.get("seed", ""), started=state.get("now", ""),
            refine_done=bool(state.get("done")), questions=len(qs), answered=len(answers),
            pack_nodes=packs.get(ctx, 0), understanding=bank.read_understanding(ctx) is not None,
            lessons=lessons.get(ctx, 0), artifacts=len(_read_artifacts(bank, ctx)),
        ))
    summaries.sort(key=lambda s: s.started, reverse=True)
    summaries = summaries[:limit]
    if not summaries:
        return "No runs found (memory/refine/ is empty)."
    head = ("| context_id | seed | started | refine? | answered/asked | pack | brief? | lessons | artifacts |\n"
            "|---|---|---|---|---|---|---|---|---|")
    return f"# Runs ({len(summaries)})\n\n{head}\n" + "\n".join(s.row() for s in summaries)


def get_run(bank, context_id: str) -> str:
    """Full structured detail for one run (F1) — a composition of the existing read paths."""
    from common.testplan import memory as tpd_store

    state = bank.read_refine_state(context_id)
    understanding = bank.read_understanding(context_id)
    questions = bank.read_questions(context_id)
    answers = bank.read_answers(context_id)
    pack = load_pack(bank, context_id)
    kinds: dict[str, int] = {}
    for n in pack.notes:
        kinds[n.type] = kinds.get(n.type, 0) + 1
    known = bool(state) or understanding is not None or questions or answers or pack.notes
    if not known:
        return (f"No such run: {context_id!r}. Nothing under {_REFINE_PREFIX}{_slug(context_id)}/ "
                f"— check `list-runs` for known ids.")
    run_logs = [b.name for b in _store(bank).iter_blobs(_RUNS_PREFIX)
                if context_id in b.name and b.name.endswith(".md")]
    lessons = [{"kind": i.kind, "statement": i.statement}
               for i in iter_lessons(bank) if i.context_id == context_id]
    detail = RunDetail(
        context_id=context_id, seed=state.get("seed", ""), started=state.get("now", ""),
        refine_done=bool(state.get("done")), understanding=understanding or "",
        questions=questions, answers=answers, pack_kinds=kinds, pack_nodes=len(pack.notes),
        plan_brief=tpd_store.read_plan_brief(bank, context_id) or "",
        scenarios_md=tpd_store.read_scenarios_md(bank, context_id) or "",
        coverage_md=tpd_store.read_coverage_md(bank, context_id) or "",
        run_logs=sorted(run_logs), lessons=lessons,
        artifacts=get_artifacts(bank, context_id),
    )
    return detail.md()


# --- per-run artifact registry (published-report URLs, recorded client-side) -----------------------

def _artifacts_path(context_id: str) -> str:
    return f"{_RUNS_PREFIX}{_slug(context_id)}/artifacts.json"


def _read_artifacts(bank, context_id: str) -> list[dict]:
    """The raw append-order list (oldest first). Missing or corrupt blob → empty (never raises)."""
    blob = _store(bank).get_blob(_artifacts_path(context_id))
    if blob is None:
        return []
    try:
        items = json.loads(blob.download_as_text())
    except (ValueError, TypeError):
        return []
    return items if isinstance(items, list) else []


def get_artifacts(bank, context_id: str) -> list[dict]:
    """Recorded report artifacts for a run, newest first (missing/corrupt → [])."""
    return list(reversed(_read_artifacts(bank, context_id)))


def record_artifact(bank, context_id: str, kind: str, url: str, title: str = "") -> str:
    """Append {kind,url,title,ts} to the run's append-only artifact registry; dedupe on url.

    Reports are published client-side (a separate Artifact tool), so the agent never sees the URL
    unless a tool records it here — this is that tool. Retrieve later via `get_run` / `get_artifacts`.
    """
    from common.adk.events import now  # lazy: keep this admin module framework-neutral / offline

    if not context_id or not url:
        return "record-artifact: need a context_id and a url."
    items = _read_artifacts(bank, context_id)
    if any(a.get("url") == url for a in items):
        return f"Artifact already recorded for {context_id}: {url}"
    items.append({"kind": kind or "report", "url": url, "title": title or "", "ts": now()})
    _store(bank).blob(_artifacts_path(context_id)).upload_from_string(
        json.dumps(items, ensure_ascii=False), "application/json")
    return f"Recorded {kind or 'report'} artifact for {context_id} ({len(items)} total): {url}"


# --- F3: cross-run comparison (COMMON vs DIVERGENT) ------------------------------------------------

_CMP_CAP = 25  # items listed per bucket per layer — keeps the diff bounded


def _bullets(text: str | None) -> set[str]:
    """Normalised bullet lines of a brief, for set comparison (drop headers / table rows / short noise)."""
    out: set[str] = set()
    for line in (text or "").splitlines():
        s = line.strip().lstrip("-*•> ").strip()
        if len(s) > 3 and not s.startswith(("#", "|")):
            out.add(s)
    return out


def _plan_items(bank, ctx: str) -> set[str]:
    from common.testplan import memory as tpd_store

    plan = tpd_store.read_plan(bank, ctx)
    if plan is None:
        return set()
    return ({f"method: {m}" for m in plan.methodology or []}
            | {f"scope: {s}" for s in plan.scope or []}
            | {f"metric: {m}" for m in plan.metrics or []})


def _scenario_keys(bank, ctx: str) -> set[str]:
    """Scenario identity independent of the run id: kind + the title's subject (before the ' — kind')."""
    from common.testplan import memory as tpd_store

    return {f"[{s.kind}] {s.title.split(' — ')[0].strip()}"
            for s in (tpd_store.read_scenarios(bank, ctx) or [])}


def _lesson_stmts(bank, ctx: str) -> set[str]:
    return {i.statement for i in iter_lessons(bank) if i.context_id == ctx}


def _run_exists(bank, ctx: str) -> bool:
    return bool(bank.read_refine_state(ctx) or bank.read_understanding(ctx)
                or bank.read_questions(ctx) or load_pack(bank, ctx).notes)


def _pct(n: int, d: int) -> str:
    return f"{100 * n // d}%" if d else "n/a"


def _bucket(label: str, items: list[str]) -> list[str]:
    out = [f"**{label} ({len(items)})**"]
    if not items:
        return out + ["_none_"]
    out += [f"- {x}" for x in items[:_CMP_CAP]]
    if len(items) > _CMP_CAP:
        out.append(f"… (+{len(items) - _CMP_CAP} more)")
    return out


def _prompt_pins(bank, ctx: str) -> dict:
    """The prompt key -> version map a run was pinned to (empty for runs predating P7)."""
    from common.testplan import memory as tp

    try:
        return tp.read_prompt_versions(bank, ctx) or {}
    except Exception:  # noqa: BLE001 — provenance is an overlay, never breaks the report
        return {}


def _assured_score(bank, ctx: str):
    """The run's best assured judge score, or None when the loop never scored it."""
    from common.testplan import memory as tp

    try:
        return (tp.read_assured_state(bank, ctx) or {}).get("final_score")
    except Exception:  # noqa: BLE001
        return None


def _prompt_section(bank, a: str, b: str) -> list[str]:
    """P7 — attribute a score difference to the prompts each run actually used.

    Without this, two runs of the same ticket differ for unknown reasons (model variance? prompt
    edit?). With the pins recorded per run, a score delta across differing prompt versions is an
    EXPERIMENT; across identical versions it is variance. Say which, explicitly."""
    pa, pb = _prompt_pins(bank, a), _prompt_pins(bank, b)
    if not pa and not pb:
        return []
    sa, sb = _assured_score(bank, a), _assured_score(bank, b)
    differing = sorted(k for k in set(pa) | set(pb) if pa.get(k, 0) != pb.get(k, 0))
    out = ["", "## Prompt versions — what each run actually ran"]
    out += [(f"- assured score: {a} = {sa if sa is not None else 'n/a'} · "
             f"{b} = {sb if sb is not None else 'n/a'}")]
    if not differing:
        out += [("- **Identical prompt versions** — any score difference here is model variance, "
                 "not a prompt change.")]
        return out
    out += ["- **Prompts differ** — the score delta is attributable to these keys:", "",
            f"| key | {a} | {b} |", "|---|---|---|"]
    out += [f"| `{k}` | v{pa.get(k, 0)} | v{pb.get(k, 0)} |" for k in differing]
    if sa is not None and sb is not None:
        better, delta = (b, sb - sa) if sb > sa else (a, sa - sb)
        out += ["", (f"- Higher score: **{better}** (+{delta:.3f}). Treat as one observation, not "
                     "proof — re-run before adopting a prompt version on that basis.")]
    return out


def compare_runs(bank, context_a: str, context_b: str) -> str:
    """F3 — diff two runs of the same ticket into COMMON (stable across runs) vs DIVERGENT (only in one).

    A read-only cross-run consensus view over understanding / plan / scenarios / lessons: a high common
    ratio means the run is reproducible (trust it); divergence flags drift or model variance to review."""
    if context_a == context_b:
        return "Provide two DIFFERENT run ids: compare-runs <ctx-a> <ctx-b>."
    missing = [c for c in (context_a, context_b) if not _run_exists(bank, c)]
    if missing:
        return f"No such run(s): {', '.join(missing)} — check `list-runs` for known ids."

    layers = [
        ("Understanding", _bullets(bank.read_understanding(context_a)),
         _bullets(bank.read_understanding(context_b))),
        ("Test plan", _plan_items(bank, context_a), _plan_items(bank, context_b)),
        ("Scenarios", _scenario_keys(bank, context_a), _scenario_keys(bank, context_b)),
        ("Lessons", _lesson_stmts(bank, context_a), _lesson_stmts(bank, context_b)),
    ]
    body: list[str] = []
    agree_sum = union_sum = 0
    for title, a, b in layers:
        common, only_a, only_b = sorted(a & b), sorted(a - b), sorted(b - a)
        union = len(a | b)
        agree_sum, union_sum = agree_sum + len(common), union_sum + union
        body.append(f"\n## {title} — {len(common)}/{union} common ({_pct(len(common), union)})")
        body += _bucket("Common (stable)", common)
        body += _bucket(f"Only in {context_a}", only_a)
        body += _bucket(f"Only in {context_b}", only_b)

    body += _prompt_section(bank, context_a, context_b)

    head = [f"# Compare runs: {context_a} vs {context_b}", "",
            (f"**Consensus {agree_sum}/{union_sum} ({_pct(agree_sum, union_sum)})** — higher = more "
             "stable across runs; divergence flags drift or model variance to review.")]
    report = "\n".join(head + body)
    if len(report) > _TOTAL_CAP:
        report = report[:_TOTAL_CAP] + f"\n\n… [compare-runs report capped at {_TOTAL_CAP} chars]"
    return report
