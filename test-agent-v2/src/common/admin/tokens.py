"""Token-usage admin (F5) — what a run actually spent, what a run is likely to spend, and the
lessons that cut spend without costing quality.

Why this lives in `admin` and not in `common.llm.meter`: the meter is a live in-process counter with
no idea what a MemoryBank is, and it is wiped when the Cloud Run instance recycles. These are the
*operator* views over that data — they read and write the bank, exactly like `runs.py` and
`memory_view.py`, and stay pure functions over it.

The persisted blob is the source of truth for anything historical. One Cloud Run instance serves
many requests and dies without warning, so a question like "what did run X cost?" can only be
answered from storage — `persist_usage` is what makes the in-memory counters outlive the process.
"""

from __future__ import annotations

import json

from common.admin._shared import _store
from common.llm import meter
from common.models import TOKEN_SAVING
from common.monitoring import get_logger

log = get_logger("admin.tokens")

TOKENS_PREFIX = "memory/tokens"

_FIELDS = ("calls", "input", "output", "cache_read", "cache_write")


def _path(run_id: str) -> str:
    return f"{TOKENS_PREFIX}/{run_id}.json"


def _merge(into: dict, add: dict) -> dict:
    """Sum two {label: {field: n}} maps. Used both to fold a new snapshot into a stored one and to
    aggregate across runs."""
    for label, usage in add.items():
        if label == "TOTAL":
            continue  # a derived row — recomputed, never accumulated (double-counts otherwise)
        row = into.setdefault(label, dict.fromkeys(_FIELDS, 0))
        for f in _FIELDS:
            row[f] = row.get(f, 0) + int(usage.get(f, 0) or 0)
    return into


def _with_total(by_label: dict) -> dict:
    total = dict.fromkeys(_FIELDS, 0)
    for label, row in by_label.items():
        if label == "TOTAL":
            continue
        for f in _FIELDS:
            total[f] += int(row.get(f, 0) or 0)
    return {**{k: v for k, v in by_label.items() if k != "TOTAL"}, "TOTAL": total}


def persist_usage(bank, run_id: str, snap: dict | None = None) -> dict:
    """Fold this process's counters for `run_id` into the run's stored blob and return the merged map.

    ACCUMULATES rather than overwrites: a run is chunked across several MCP calls (the assured loop
    pauses and resumes, a re-run continues a context), so overwriting would keep only the last chunk.

    DRAINS the counters it folds in. They are process-cumulative, and consecutive chunks of one run
    usually land on the SAME warm instance — so an un-drained snapshot re-adds every earlier chunk on
    top of what storage already holds (3 chunks stored 2x the real bill; the admin view, which reads
    storage *and* the live counters, showed 3x)."""
    snap = meter.snapshot(run_id, drain=True) if snap is None else snap
    stored = read_usage(bank, run_id)
    merged = _with_total(_merge({k: v for k, v in stored.items() if k != "TOTAL"}, snap))
    try:
        bank.put_text(_path(run_id), json.dumps(merged, indent=1))
    except Exception as exc:  # noqa: BLE001 — accounting must never break the pipeline it measures
        log.warning("tokens: persist for %s failed (%s)", run_id, exc)
    return merged


def read_usage(bank, run_id: str) -> dict:
    """The stored {label: usage} map for one run, or {} when nothing was recorded."""
    try:
        raw = bank.get_text(_path(run_id))
    except Exception as exc:  # noqa: BLE001
        log.warning("tokens: read for %s failed (%s)", run_id, exc)
        return {}
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        log.warning("tokens: stored blob for %s is not valid JSON", run_id)
        return {}


def _run_ids(bank) -> list[str]:
    """Run ids with a stored blob (same `iter_blobs` idiom as runs.py / backup.py)."""
    try:
        names = [b.name for b in _store(bank).iter_blobs(f"{TOKENS_PREFIX}/")]
    except Exception as exc:  # noqa: BLE001
        log.warning("tokens: listing runs failed (%s)", exc)
        return []
    return sorted({n.rsplit("/", 1)[-1][: -len(".json")] for n in names if n.endswith(".json")})


def _collect(bank, ids: list[str]) -> dict:
    """Stored + still-in-memory usage for `ids`, summed into one {label: usage} map."""
    agg: dict = {}
    for rid in ids:
        _merge(agg, {k: v for k, v in read_usage(bank, rid).items() if k != "TOTAL"})
        _merge(agg, meter.snapshot(rid))
    return agg


def _fmt(by_label: dict, *, title: str, per_label: bool = True) -> str:
    rows = _with_total(by_label)
    total = rows["TOTAL"]
    cached = total["cache_read"] + total["cache_write"]
    hit = total["cache_read"] / cached if cached else 0.0
    billed = total["input"] + cached
    out = [title, ""]
    if per_label:
        out.append(f"{'stage / agent':<34}{'calls':>7}{'input':>10}{'cached_rd':>11}"
                   f"{'cached_wr':>11}{'output':>10}")
        out.append("-" * 83)
        ordered = sorted(((k, v) for k, v in rows.items() if k != "TOTAL"),
                         key=lambda kv: -(kv[1]["input"] + kv[1]["cache_read"] + kv[1]["cache_write"]))
        for label, r in ordered:
            out.append(f"{label[:33]:<34}{r['calls']:>7}{r['input']:>10}{r['cache_read']:>11}"
                       f"{r['cache_write']:>11}{r['output']:>10}")
        out.append("-" * 83)
        out.append(f"{'TOTAL':<34}{total['calls']:>7}{total['input']:>10}{total['cache_read']:>11}"
                   f"{total['cache_write']:>11}{total['output']:>10}")
        out.append("")
    out.append(f"billed input {billed} (of which {cached} cached) · output {total['output']} "
               f"· cache-hit {hit:.0%}")
    if cached and hit < 0.2:
        out.append("WARNING: cache-hit under 20% — the prefix is probably drifting between calls, "
                   "or it is under the model's minimum cacheable size. See "
                   "docs/PROPOSAL-llm-token-optimization.md §6b.")
    return "\n".join(out)


def token_usage(bank, run_id: str = "") -> str:
    """Overall usage, or one run's when `run_id` is given."""
    if run_id:
        agg = _collect(bank, [run_id])
        return (_fmt(agg, title=f"Token usage — run {run_id}") if agg
                else f"token-usage: nothing recorded for {run_id}.")
    ids = _run_ids(bank)
    agg = _collect(bank, ids)
    _merge(agg, meter.snapshot())  # include anything this process has not persisted yet
    if not agg:
        return "token-usage: nothing recorded yet."
    return _fmt(agg, title=f"Token usage — overall ({len(ids)} stored run(s))")


def token_by_agent(bank, run_ids: list[str] | None = None) -> str:
    """The same per-label breakdown, narrowed to the runs you name — "which agent is expensive, and
    is that true for THIS ticket or in general?". No run ids = every stored run."""
    ids = list(run_ids or []) or _run_ids(bank)
    if not ids:
        return "token-agents: no runs recorded yet."
    agg = _collect(bank, ids)
    if not agg:
        return f"token-agents: nothing recorded for {', '.join(ids)}."
    scope = ", ".join(ids) if run_ids else f"all {len(ids)} run(s)"
    return _fmt(agg, title=f"Token usage by agent — {scope}")


# --- 2. estimate ---------------------------------------------------------------------------------

#: What one implement round costs, in CALLS, as a function of the pack. Derived from the code, not
#: guessed: llm.py batches grounded units `_BATCH_UNITS=3` at a time (capped at TPD_GEN_MAX_BATCHES),
#: plus one crosscutting call, plus one scope-classify per implement, plus TPD_JUDGE_SAMPLES judge
#: calls per assured round. Kept here (not imported) so a stale constant shows up as a wrong estimate
#: rather than an import cycle from admin into the TPD package.
_BATCH_UNITS = 3
_DEFINE_CALLS = 5          # 4 interrogation rounds + the brief
_REFINE_CALLS_PER_PASS = 4  # 3 question rounds + 1 understanding


def _tok(chars: int) -> int:
    """Characters -> tokens at the ~4 chars/token rule. An estimate, never a bill."""
    return max(0, chars // 4)


def _first_using(plan, key: str) -> str:
    """The first stage in `plan` on a given prefix — the one that pays its single cache write."""
    return next(label for label, _c, k, _p, _b in plan if k == key)


def estimate_usage(bank, context_id: str, *, assured_rounds: int = 2) -> str:
    """Project what a run WILL cost from the pack it would run against.

    This answers "is this ticket going to be expensive?" before spending anything, and — run against
    a context that already has real numbers — shows the model against the actuals so a bad estimate
    is visible rather than quietly trusted."""
    from common.interrogate.pack import load_pack
    from common.testplan.models import PlanPack

    pack = load_pack(bank, context_id)
    understanding = bank.read_understanding(context_id) or ""
    plan_pack = PlanPack(pack=pack, understanding=understanding)
    units = len(pack.grounded)
    if not units:
        return (f"token-estimate {context_id}: the pack is empty — run gather first. "
                "(An estimate needs the pack it would run against.)")

    # Key prefixes by the STRING, not by its token count: two different prefixes that happen to be
    # the same size are not the same cache entry, and a prefix match is byte-exact (§3). When the
    # two strings genuinely are identical (a pack with no confirmed understanding) they DO share one
    # entry, and this keying gets that right for free.
    kga_text, tpd_text = pack.summary_text(), plan_pack.summary_text()
    kga_prefix, tpd_prefix = _tok(len(kga_text)), _tok(len(tpd_text))
    batches = max(1, -(-units // _BATCH_UNITS))          # ceil
    gen_calls = (batches + 1) * max(1, assured_rounds)   # + crosscutting, per assured round
    judge_calls = max(1, assured_rounds)

    # (label, calls, prefix tokens, per-call body tokens) — bodies from the measured shapes in
    # docs/PROPOSAL-llm-token-optimization.md §2.
    plan = [
        ("gather.distill", units, "", 0, 2000),
        (f"refine ({_REFINE_CALLS_PER_PASS}/pass)", _REFINE_CALLS_PER_PASS, kga_text, kga_prefix, 500),
        ("define rounds + brief", _DEFINE_CALLS, tpd_text, tpd_prefix, 500),
        ("implement scope-classify", 1, tpd_text, tpd_prefix, 1100),
        ("implement generate", gen_calls, tpd_text, tpd_prefix, 700),
        ("implement judge", judge_calls, tpd_text, tpd_prefix, 2500),
        ("implement steps", 1, tpd_text, tpd_prefix, 2500),
    ]
    head = (f"Token estimate — {context_id}   ({units} grounded unit(s), "
            f"{batches} generation batch(es), {assured_rounds} assured round(s))")
    cols = f"{'stage':<30}{'calls':>7}{'uncached':>12}{'cached_rd':>12}{'cached_wr':>12}"
    out = [head, "", cols, "-" * 73]
    # The prefix is written ONCE per distinct prefix, not once per stage: every TPD stage below
    # shares the same pack_block(summary) string, so they share one cache entry (that sharing is the
    # whole point of T2/T3). Charging a write per stage overstated the bill by ~4x the prefix.
    unc = rd = 0
    sizes = {k: p for _l, _c, k, p, _b in plan if k}          # prefix string -> its token count
    wr = sum(int(p * 2.0) for p in sizes.values())            # one 1h write per DISTINCT prefix
    written: set[str] = set()
    for label, calls, key, prefix, body in plan:
        r = 0
        w = 0
        if key:
            # the very first call on a prefix writes it; every other call on it reads at 0.1x
            reads = calls if key in written else calls - 1
            if key not in written:
                written.add(key)
                w = int(prefix * 2.0) if label == _first_using(plan, key) else 0
            r = int(prefix * 0.1 * max(0, reads))
        u = body * calls
        unc += u
        rd += r
        out.append(f"{label[:29]:<30}{calls:>7}{u:>12}{r:>12}{w:>12}")
    old_ttl = unc + sum(int(p * 1.25) * c for _l, c, k, p, _b in plan if k)  # 5m: every call re-writes
    note = (f"~{unc + rd + wr} input token-equivalents. Prefix reuse assumes the 1h TTL holds across "
            f"the stage (see the proposal's §3); at the old 5m default every call would re-pay the "
            f"write instead: ~{old_ttl}.")
    tail = ("Estimate only — a projection from pack size and the call counts in the code, not a "
            f"quote. Compare with: token-usage {context_id}")
    out += ["-" * 73,
            f"{'TOTAL (billed-equivalent)':<30}{'':>7}{unc:>12}{rd:>12}{wr:>12}",
            "", note, "", tail]
    return "\n".join(out)


# --- 3. token-saving lessons --------------------------------------------------------------------

#: Lessons recorded here are ordinary Insight lessons carrying the canonical TOKEN_SAVING kind, so
#: they flow through the SAME capture/recall/govern machinery as every other lesson (`common.learn`)
#: — no parallel store. Re-exported so callers can filter on it without importing models.
TOKEN_LESSON = TOKEN_SAVING


def record_token_lesson(bank, context_id: str, statement: str, *, rationale: str = "",
                        source_refs: list[str] | None = None, now: str = "") -> str:
    """Record a lesson about cutting token spend WITHOUT losing quality.

    The quality half is the point. Anything that trades accuracy for cost is a config knob (Turbo,
    effort, iteration counts) and belongs in a tfvar, not in the lesson store — a lesson here is a
    change that was measured to be free, so a future run can apply it without re-litigating."""
    from common.learn import LessonSignal, capture_lessons

    statement = statement.strip()
    if not statement:
        return "token-lesson: provide the lesson text."
    written = capture_lessons(
        bank, context_id=context_id, run_id=context_id, step="token-optimization",
        signals=[LessonSignal(statement=statement, kind=TOKEN_LESSON, confidence="medium",
                              rationale=rationale or "recorded via admin token-lesson",
                              source_refs=list(source_refs or []))],
        now=now)
    if not written:
        return ("token-lesson: not recorded — it is a duplicate of an existing lesson, or its "
                "source_refs are not in this context's graph (capture requires grounding).")
    return f"token-lesson recorded for {context_id}: {written[0].id}\n  {written[0].statement}"
