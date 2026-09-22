# Proposal — Post-Approval Answer Amendment

**Problem.** After the user has approved the pack/plan and the report is produced, they realise an
earlier interrogation **answer was wrong**. Today the pipeline is forward-only: there is no way to
correct that one answer and re-propagate it without re-running everything and losing all other work.

## Recommended approach — append-only amend + scoped re-derivation

The pipeline is already CQRS: `answers.json` is an append-only **log**; `decisions.json`,
`plan.json`/`plan-brief.md`, `scenarios.json`, `coverage.json` are **projections** joined by
deterministic ids and `source_refs`. So correcting a run needs **no new machinery** — only a way to
append a superseding answer and re-run the projectors over the blast radius. Two client-gated moves:

1. **Record (no LLM).** Append the corrected `Answer`; re-distill a new `Insight` whose `supersedes`
   points at the old one; mark the old `status="superseded"`; swap the index node. (Mirrors the
   existing `veto_lesson` governance move — and is the **first real use of the already-declared,
   currently-dead `Insight.supersedes` field**.)
2. **Re-project only the affected slice.** Re-distill the one `PlanDecision` (deterministic id),
   re-`assemble_plan` + `restate` the brief (this **also fixes the known "free-text
   `define_plan(answer=)` doesn't update structured fields" bug** by construction), regenerate only
   the scenarios whose `source_refs` trace to the amended note via the **existing `only_ids` /
   `in_scope_ids` scoped-generation seam**, merge by id, rebuild coverage + `.feature`. Everything
   unaffected is read back byte-identical; the plan stays `confirmed`.

**Rejected:** *full re-run* (loses unaffected work, re-interrogates every round) and *overwrite-in-place*
(destroys the append-only audit log, fights the CQRS design).

**Blast radius** depends on the amended round: `scope` = per-note / narrow; `methodology` / `metrics`
/ `test-design` / `case-design` = plan-wide (they ride every scenario) but still **one generate pass,
no re-interrogation**. Traceability is answer→**note**→scenario (there is no direct answer→scenario
link), so the radius is joined through the shared note id.

## What to build

| Kind | Item | Location |
|---|---|---|
| Model field | `PlanDecision.supersedes: str = ""` (mirrors `Insight.supersedes`) | `common/testplan/models/plan.py` |
| Fn (new file) | `amend_answer(bank, store, ctx, qid, corrected, *, now)` + `blast_radius(bank, ctx, qid)` | `common/interrogate/amend.py` |
| Fn (new file) | `rederive(bank, ctx, amended_qid, *, model, now)` (in TPD — calls TPD generators) | `test_plan_definition/rederive.py` |
| Gateway tool | `amend_answer(context_id, question_id, corrected_answer)` → records + returns blast radius | `gateway/mcp_server.py` |
| Gateway tool | `rederive_plan(context_id)` → runs scoped re-projection, returns diff | `gateway/mcp_server.py` |
| Routers/bridges | `amend` / `rederive` verbs (off the loop via `to_thread`) + forwarders | KGA + TPD `agent.py` / `bridge/mcp_server.py` |
| Tests | `tests/test_amend.py`, `tests/test_rederive.py` | — |

Report re-versioning reuses the existing client-side HTML render + run-history / `compare_runs`.
Client-owned Yes/No gates on both tools, same convention as the rest of the pipeline.

## Phases

- **P0** — model field + `amend.py` (record + blast_radius) + `amend_answer` tool + test. Records the
  correction and reports the radius; no regeneration yet.
- **P1** — `rederive.py` (scoped re-projection) + `rederive_plan` tool + test. Closes the loop.
- **P2** — surface amendments in the run-history / artifact registry so a corrected run is auditable.

## Notes / doc drift found

- `RESEARCH-tpd-interrogative-coverage.md` cites pre-restructure paths (`round/base.py`,
  `define/loop.py::PlanSession`); current tree is `round/__init__.py` + `define/session.py`.
- KGA `approve` flips **no** status (pack stays mutable); only TPD `approve_plan` truly locks
  (`status→confirmed`). No destructive "unlock" is needed.
- `Insight.supersedes` is dead today; `PlanDecision` has no such field. This proposal is what wires
  supersede-on-contradiction up for answer-derived artifacts.
