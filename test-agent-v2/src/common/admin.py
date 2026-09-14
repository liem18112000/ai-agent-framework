"""Memory & history ADMIN handlers — an operator utility, NOT part of the testing pipeline.

Pure functions over a `MemoryBank` (GCS/in-memory) and the shared async SQLAlchemy `engine`:
run history (F1), memory introspection (F2), backup-as-version (F4), and a guarded wipe-all (F3).
They only READ, RESET, or COPY state that already exists — never a new source of truth. Framework-
neutral and offline-testable against `InMemoryObjectStore` + a None/fake engine.

`restore_backup`, a `scope=` on wipe, and `format=` toggles are DEFERRED (see the plan's scope trim).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from common import learn
from common.interrogate.pack import load_pack
from common.learn.store import iter_lessons
from common.memory.bank import ROOT, _slug
from common.models import INSIGHT
from common.monitoring import get_logger

log = get_logger("admin")

_REFINE_PREFIX = f"{ROOT}/refine/"
_RUNS_PREFIX = f"{ROOT}/runs/"
_BACKUPS_ROOT = "memory-backups"


def _store(bank):
    """The ObjectStore behind a MemoryBank — admin needs list/delete/copy at the blob layer (§3)."""
    return bank._bucket


# --- F1: run history -------------------------------------------------------------------------------

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

    def row(self) -> str:
        return (f"| {self.context_id} | {self.seed or '-'} | {self.started or '-'} | "
                f"{'yes' if self.refine_done else 'no'} | {self.answered}/{self.questions} | "
                f"{self.pack_nodes} | {'yes' if self.understanding else 'no'} | {self.lessons} |")


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

    def md(self) -> str:
        qs, ans = self.questions or [], self.answers or []
        out = [f"# Run {self.context_id}", ""]
        out.append(f"- seed: {self.seed or '-'}")
        out.append(f"- started: {self.started or '-'}")
        out.append(f"- refine done: {'yes' if self.refine_done else 'no'}")
        out.append(f"- pack: {self.pack_nodes} nodes ({_kinds_str(self.pack_kinds or {})})")
        out.append("")
        out.append("## Understanding brief")
        out.append(self.understanding.strip() if self.understanding else "_none yet_")
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
        out.append(self.plan_brief.strip() if self.plan_brief else "_no plan yet_")
        out.append("")
        out.append("## Scenarios")
        out.append(self.scenarios_md.strip() if self.scenarios_md else "_no scenarios yet_")
        out.append("")
        out.append("## Coverage matrix")
        out.append(self.coverage_md.strip() if self.coverage_md else "_no coverage yet_")
        out.append("")
        out.append("## Run logs")
        out.extend(f"- {r}" for r in (self.run_logs or ["_none_"]))
        out.append("")
        out.append(f"## Lessons captured ({len(self.lessons or [])})")
        out.extend(f"- [{lsn['kind']}] {lsn['statement']}" for lsn in (self.lessons or []))
        if not self.lessons:
            out.append("_none_")
        out.append("")
        out.append("_Eval scores are computed on demand via evaluate_pack / evaluate_plan; not stored._")
        return "\n".join(out)


def _kinds_str(kinds: dict) -> str:
    return ", ".join(f"{k}:{v}" for k, v in sorted(kinds.items())) or "empty"


def _run_contexts(bank) -> list[str]:
    """The known runs — one dir under memory/refine/ per context (computed on read, no sidecar index)."""
    ctxs: set[str] = set()
    for blob in _store(bank).iter_blobs(_REFINE_PREFIX):
        top = blob.name[len(_REFINE_PREFIX):].split("/", 1)[0]
        if top and top != "_sessions":
            ctxs.add(top)
    return sorted(ctxs)


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
            lessons=lessons.get(ctx, 0),
        ))
    summaries.sort(key=lambda s: s.started, reverse=True)
    summaries = summaries[:limit]
    if not summaries:
        return "No runs found (memory/refine/ is empty)."
    head = ("| context_id | seed | started | refine? | answered/asked | pack | brief? | lessons |\n"
            "|---|---|---|---|---|---|---|---|")
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
    run_logs = [b.name for b in _store(bank).iter_blobs(_RUNS_PREFIX) if context_id in b.name]
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
    )
    return detail.md()


# --- F2: memory introspection (four tiers) ---------------------------------------------------------

async def view_memory(bank, engine, tier: str = "all", context_id: str | None = None) -> str:
    """View the four memory tiers (F2): working / episodic / semantic / procedural.

    `engine` is the shared async SQLAlchemy engine (or None). DB-backed rows degrade gracefully when
    no DB is configured. `tier="all"` runs every section (skipping working without a context_id)."""
    tier = (tier or "all").lower()
    sections: list[str] = []
    if tier in ("all", "working"):
        sections.append(await asyncio.to_thread(_view_working, bank, context_id))
    if tier in ("all", "episodic"):
        sections.append(await _view_episodic(bank, engine, context_id))
    if tier in ("all", "semantic"):
        sections.append(await _view_semantic(bank, engine))
    if tier in ("all", "procedural"):
        sections.append(_view_procedural())
    if not sections:
        return f"Unknown tier {tier!r}. Use: all | working | episodic | semantic | procedural."
    return "\n\n".join(sections)


def _view_working(bank, context_id: str | None) -> str:
    """Working (in-context) memory = the per-context refine working set (ADK session state lives in the
    DB session table, surfaced via the semantic/episodic DB counts)."""
    if not context_id:
        runs = _run_contexts(bank)
        return ("## Working (in-context)\nProvide a context_id. Known runs: "
                + (", ".join(runs) if runs else "none") + ".")
    state = bank.read_refine_state(context_id)
    qs = bank.read_questions(context_id)
    answers = bank.read_answers(context_id)
    understanding = bank.read_understanding(context_id)
    return (f"## Working (in-context) — {context_id}\n"
            f"- refine state: {'done' if state.get('done') else ('active pass ' + str(state.get('pass', '?'))) if state else 'none'}\n"
            f"- pending rounds: {', '.join(state.get('pending', [])) or '-'}\n"
            f"- questions: {len(qs)}  answers: {len(answers)}\n"
            f"- understanding brief: {'present' if understanding else 'none'}")


async def _view_episodic(bank, engine, context_id: str | None) -> str:
    """Episodic = what happened: recent run logs + captured lessons + A2A task rows."""
    logs, lessons = await asyncio.to_thread(_episodic_bank_reads, bank)  # blocking GCS off the loop
    lines = ["## Episodic (history)", f"- run logs: {len(logs)}"]
    lines += [f"    - {name}" for name in logs[:10]]
    lines.append(f"- lessons captured: {len(lessons)}")
    if engine is None:
        lines.append("- A2A tasks: (in-memory, no DB configured)")
    else:
        count = await _first_table_count(engine, ("tasks", "task"))
        lines.append(f"- A2A task rows: {count if count is not None else 'n/a (no task table)'}")
    return "\n".join(lines)


def _episodic_bank_reads(bank) -> tuple[list[str], list]:
    """The blocking GCS reads for the episodic tier — run in a thread (run logs + lessons)."""
    logs = sorted((b.name[len(_RUNS_PREFIX):] for b in _store(bank).iter_blobs(_RUNS_PREFIX)), reverse=True)
    return logs, learn.search_lessons(bank)


async def _view_semantic(bank, engine) -> str:
    """Semantic = generalised facts: the GCS index + the pgvector projection, with a drift signal."""
    graph, _ = await asyncio.to_thread(bank.load_index)  # blocking GCS off the loop
    by_type: dict[str, int] = {}
    for n in graph.nodes.values():
        by_type[n.get("type", "?")] = by_type.get(n.get("type", "?"), 0) + 1
    lines = ["## Semantic (facts)",
             f"- index nodes: {len(graph.nodes)} ({_kinds_str(by_type)})",
             f"- index edges: {len(graph.edges)}"]
    if engine is None:
        lines.append("- pgvector: (no DB configured — GCS index is the sole tier)")
        return "\n".join(lines)
    node_rows = await _first_table_count(engine, ("memory_node",))
    edge_rows = await _first_table_count(engine, ("memory_edge",))
    lines.append(f"- pgvector memory_node rows: {node_rows if node_rows is not None else 'n/a'}")
    lines.append(f"- pgvector memory_edge rows: {edge_rows if edge_rows is not None else 'n/a'}")
    if node_rows is not None and node_rows != len(graph.nodes):
        lines.append(f"- ⚠ drift: index has {len(graph.nodes)} nodes but pgvector has {node_rows} "
                     f"(rebuild via pg/backfill.py)")
    return "\n".join(lines)


# ponytail: static mirror of the pipeline tool surfaces — common must not import the agent packages
# (that would be a common→agent back-dependency). Kept short; update if a bridge's tool set changes.
_PROCEDURAL_AGENTS = (
    ("knowledge_gathering", "crawl + distill + interrogate a ticket into the pack",
     ("gather_knowledge", "gather_codebase", "refine", "get_questions", "get_understanding",
      "search_memory", "get_note", "search_lessons", "veto_lesson", "approve")),
    ("test_plan_definition", "define + implement the test plan from the pack",
     ("define_plan", "get_plan", "approve_plan", "implement_plan", "get_scenarios", "get_coverage")),
    ("test_evaluation", "score the pack / plan (read-only quality gate)",
     ("evaluate_pack", "evaluate_plan")),
    ("admin_agent", "[ADMIN — non-pipeline] memory & history operator utility",
     ("list_runs", "get_run", "view_memory", "backup_memory", "list_backups", "wipe_all")),
)


def _view_procedural() -> str:
    """Procedural = how the agents operate: agents + tool names + interrogation rounds. Static, no DB."""
    lines = ["## Procedural (rules / skills)"]
    for name, role, toolnames in _PROCEDURAL_AGENTS:
        lines.append(f"- **{name}** — {role}")
        lines.append(f"    tools: {', '.join(toolnames)}")
    lines.append(f"- interrogation rounds: {', '.join(_interrogation_rounds())}")
    lines.append("- assured-loop rubric: generate→judge→gate→reflect→regenerate (TPD_ASSURED)")
    return "\n".join(lines)


def _interrogation_rounds() -> list[str]:
    import pkgutil

    from common.interrogate import round as round_pkg

    return sorted(m.name for m in pkgutil.iter_modules(round_pkg.__path__) if m.name != "base")


# --- shared DB helpers (async engine) --------------------------------------------------------------

async def _table_names(engine) -> list[str]:
    """Reflected table names on the shared engine (run over a sync connection via run_sync)."""
    from sqlalchemy import inspect

    async with engine.connect() as conn:
        return await conn.run_sync(lambda c: inspect(c).get_table_names())


async def _first_table_count(engine, candidates: tuple[str, ...]) -> int | None:
    """Row count of the first of `candidates` that exists, or None when none do."""
    from sqlalchemy import text

    names = set(await _table_names(engine))
    table = next((c for c in candidates if c in names), None)
    if table is None:
        return None
    async with engine.connect() as conn:
        return (await conn.execute(text(f'SELECT count(*) FROM "{table}"'))).scalar() or 0


# --- F4: backup memory as a version ----------------------------------------------------------------

def _copy_blob(store, src: str, dst: str) -> int:
    """Copy one blob src→dst through the port (read+write); return its byte size.

    ponytail: read+write is uniform across GCS/in-memory and the bank blobs are small text; a
    server-side copy is used only if the store exposes copy_blob (no adapter does today)."""
    if hasattr(store, "copy_blob"):
        store.copy_blob(src, dst)
        blob = store.get_blob(src)
        return len(blob.download_as_text().encode("utf-8")) if blob else 0
    data = store.get_blob(src).download_as_text()
    store.blob(dst).upload_from_string(data, content_type="application/octet-stream")
    return len(data.encode("utf-8"))


def backup_memory(bank, summary: str, *, now: datetime | None = None) -> str:
    """Snapshot memory/** to memory-backups/<version>/ + a MANIFEST.json (F4). pgvector is NOT copied
    (it rebuilds from the bank via pg/backfill.py). `now` is injectable for deterministic tests."""
    dt = now or datetime.now(UTC)
    version = f"{dt.strftime('%Y-%m-%dT%H-%M-%SZ')}_{_slug(summary) or 'backup'}"
    dest_root = f"{_BACKUPS_ROOT}/{version}"
    store = _store(bank)
    blob_count = 0
    byte_size = 0
    for blob in list(store.iter_blobs(f"{ROOT}/")):
        byte_size += _copy_blob(store, blob.name, f"{dest_root}/{blob.name}")
        blob_count += 1
    manifest = {"datetime": dt.isoformat(), "summary": summary, "blob_count": blob_count,
                "byte_size": byte_size, "source_prefix": f"{ROOT}/"}
    store.blob(f"{dest_root}/MANIFEST.json").upload_from_string(
        json.dumps(manifest, indent=1, ensure_ascii=False), content_type="application/json")
    return (f"Backed up {blob_count} blobs ({byte_size} bytes) → {dest_root}/\n"
            f"(pgvector not copied — rebuild from the bank via pg/backfill.py.)")


def list_backups(bank) -> str:
    """Every memory-backups/*/MANIFEST.json, newest first (F4)."""
    store = _store(bank)
    manifests: list[dict] = []
    for blob in store.iter_blobs(f"{_BACKUPS_ROOT}/"):
        if not blob.name.endswith("/MANIFEST.json"):
            continue
        version = blob.name[len(_BACKUPS_ROOT) + 1: -len("/MANIFEST.json")]
        try:
            m = json.loads(blob.download_as_text())
        except (ValueError, KeyError):
            continue
        m["version"] = version
        manifests.append(m)
    if not manifests:
        return "No backups yet. Create one with backup_memory(summary)."
    manifests.sort(key=lambda m: m.get("datetime", ""), reverse=True)
    head = "| version | datetime | summary | blobs | bytes |\n|---|---|---|---|---|"
    rows = [f"| {m['version']} | {m.get('datetime', '-')} | {m.get('summary', '-')} | "
            f"{m.get('blob_count', 0)} | {m.get('byte_size', 0)} |" for m in manifests]
    return f"# Backups ({len(manifests)})\n\n{head}\n" + "\n".join(rows)


# --- F3: wipe-all (DESTRUCTIVE, guarded) -----------------------------------------------------------

def wipe_required_token() -> str:
    """The confirm token `wipe_all` demands: the GCS_BUCKET value, or literal 'WIPE' when unset."""
    import os

    return os.environ.get("GCS_BUCKET") or "WIPE"


async def wipe_all(bank, engine, confirm: str, *, required_token: str | None = None) -> str:
    """DESTRUCTIVE (F3): clear the memory bank, pgvector, and the A2A task + ADK session tables in one
    guarded call. Requires `confirm` == the required token (GCS_BUCKET, or 'WIPE' when unset).

    Never touches memory-backups/** — a backup survives a wipe on purpose. Idempotent: a second call
    reports zero. pgvector/task/session tables are TRUNCATEd (not dropped) so the schema survives."""
    required = required_token or wipe_required_token()
    if not confirm or confirm != required:
        return (f"REFUSED — wipe_all is destructive. Re-call with confirm={required!r} "
                f"(the exact token required to proceed).")

    report = ["# Wipe-all report"]

    # 1) memory bank — leaves memory-backups/** untouched (trailing-slash prefix excludes it).
    removed = bank.delete_prefix(f"{ROOT}/")
    report.append(f"- memory bank: {removed} blobs removed (memory-backups/** preserved)")

    # 2/3) pgvector + the a2a/adk tables on the shared engine.
    if engine is None:
        report.append("- pgvector: in-memory, nothing persisted")
        report.append("- task/session store: in-memory, nothing persisted")
        return "\n".join(report)

    from sqlalchemy import text

    names = await _table_names(engine)
    pg_tables = [t for t in ("memory_node", "memory_edge") if t in names]
    other_tables = [t for t in names if t not in pg_tables]
    async with engine.begin() as conn:
        pg_rows = await _truncate(conn, text, pg_tables)
        other_rows = await _truncate(conn, text, other_tables)
    report.append(f"- pgvector: {pg_rows} rows truncated ({', '.join(pg_tables) or 'no tables'})")
    report.append(f"- task/session store: {other_rows} rows truncated "
                  f"({', '.join(other_tables) or 'no tables'})")
    return "\n".join(report)


async def _truncate(conn, text, tables: list[str]) -> int:
    """Count then TRUNCATE `tables` (CASCADE, one statement — FK-safe); return rows removed."""
    if not tables:
        return 0
    total = 0
    for t in tables:
        total += (await conn.execute(text(f'SELECT count(*) FROM "{t}"'))).scalar() or 0
    quoted = ", ".join(f'"{t}"' for t in tables)
    await conn.execute(text(f"TRUNCATE TABLE {quoted} CASCADE"))
    return total
