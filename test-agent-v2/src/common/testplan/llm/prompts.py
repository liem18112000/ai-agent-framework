"""Prompt templates for the Claude-on-Vertex plan generators."""

from __future__ import annotations

from common.testplan.llm import templates
from common.testplan.models import ROUND_PREFIX, TestData, TestPlan, TestScenario, effective_kinds

ROUND_FOCUS = {
    "methodology": (
        "the test methodology (API / E2E / UI) that fits THIS feature. API is the deterministic "
        "default; reach for E2E only where the value lives in a multi-service flow the API layer "
        "can't prove alone (async pipelines, cross-service side effects, real downstream that must "
        "actually run), and UI only when the behaviour is genuinely UI-bound. Ground the call in "
        "the feature's real surface (REST endpoints, async jobs, storage) — name it. Surface a "
        "question only where two methodologies would verify materially different things; otherwise "
        "self-answer with the recommendation. Methodology judgement only, not test steps."
    ),
    "scope": (
        "what is under test and what is explicitly OUT. Name the concrete in-scope behaviours from "
        "the pack (not just the feature title). Out-of-scope-for-gathering is NOT out-of-scope-for-"
        "testing: a recorded-but-unfollowed integration may still be load-bearing — ask per such "
        "integration. Flag sibling/framework tickets and adjacent features as explicit exclusions "
        "so the suite has a hard boundary. Scope judgement, not implementation detail."
    ),
    "metrics": (
        "what 'passed' MEANS and the coverage bar. Pass = action accepted (fast, shallow) vs "
        "end-state verified (assert the real stored/returned outcome) — prefer end-state, and tie "
        "it to an observable the pack names (stored field, job-report counter, response body). Set "
        "the coverage bar PER RISK: high-risk behaviours (auth, data-loss, compliance, money) earn "
        "negative + boundary + error above the floor; low-risk behaviours get happy + the floor. "
        "Surface the genuine bar/where-to-go-deeper calls; self-answer the settled ones. Quality "
        "over scenario count."
    ),
    "test-design": (
        "the test-design METHOD(s) that will enumerate the cases toward 100% coverage. RECOMMEND from "
        "the feature's shape in the pack + the earlier methodology/scope/metrics decisions: input "
        "domains with ranges/formats → Equivalence Partitioning + Boundary Value Analysis; "
        "combinational rules (eligibility/pricing/auth matrix) → decision table; a lifecycle/status "
        "machine → state-transition; many independent parameters/flags → pairwise (t-way); several "
        "dependencies → error-path/fault-injection; money/auth/compliance risk → risk-based depth. "
        "ALSO ask the user to ADD any test kinds the pack can't infer (security, performance, "
        "concurrency, accessibility, i18n, migration…). Pre-fill your recommendation as the answer; "
        "surface it as one open judgement call, not busywork."
    ),
}


# P0 — Gherkin best-practice grounding injected into the scenario/steps generators. Declarative,
# one-behaviour-per-scenario, business language, independent scenarios, concrete data (no glue).
GHERKIN_GUIDELINES = (
    "Gherkin best practices:\n"
    "- One behaviour per scenario; keep it atomic and independently runnable (no ordering between "
    "scenarios, no shared mutable state).\n"
    "- Declarative, business language (WHAT is verified), not imperative UI/API glue (HOW to click "
    "or which endpoint) — the step layer owns the mechanics.\n"
    "- Exactly one When (the action under test); Given arranges preconditions, Then asserts an "
    "OBSERVABLE outcome (a stored field, a response body/status, a counter) — never 'it works'.\n"
    "- Title states the behaviour + case, e.g. 'Reject payment when the account is over its limit'.\n"
    "- Prefer concrete, grounded example values over placeholders; reuse the given test-data ids.\n"
)

# P0 — RESTGPT-style enrichment: the approved pack IS our spec surface. Mine it for concrete values,
# rules and error/boundary conditions; never invent a requirement the pack does not support.
PACK_GROUNDING = (
    "Ground every scenario in the pack: derive concrete example values, business rules, and the "
    "boundary / error conditions from the pack's acceptance criteria, notes and insights. Do NOT "
    "invent requirements, endpoints, fields or limits the pack does not state — an unsupported "
    "scenario is worse than a missing one. Cite the note/insight id you drew each scenario from.\n"
)


def revision_feedback(reflections: list[str] | None) -> str:
    """A REVISION block appended by the assured loop — the judge's imperative fixes from the last
    attempt (§3.4 reflexion). Empty string on the first pass so the default prompt is unchanged."""
    if not reflections:
        return ""
    items = "\n".join(f"- {r}" for r in reflections)
    return ("\nREVISION FEEDBACK — the previous attempt was judged below the quality bar. Address "
            f"EACH of these before returning, without dropping coverage you already had:\n{items}\n")


def pack_block(summary: str) -> str:
    """The context-pack block appended to the plan prompts. When `include_context=False` the caller
    passes THIS string as `complete(cache_prefix=…)` instead — identical across the define rounds +
    brief for one context, so Anthropic prompt-caches it (a hit after round 1)."""
    return f"Context pack:\n{summary}"


def _render(key: str, params: dict) -> str:
    """Render a stored template. The store is Cloud SQL-backed when a DB is configured and falls back
    to the bodies in ``templates.DEFAULTS`` otherwise — so this is a no-op change offline."""
    from common.prompts import store_for
    from common.testplan.llm.templates import DEFAULTS

    return store_for(DEFAULTS).get(key).render(params)


async def refresh_store() -> dict:
    """P2/P4 — load the published snapshot ONCE per run and return the pinned versions.

    Every ``_render`` afterwards reads that snapshot, so a publish landing mid-run cannot make
    round 3 incomparable to round 1. The returned mapping goes on the run log as provenance.
    Best-effort: on any store failure the Python defaults keep serving."""
    from common.prompts import store_for
    from common.testplan.llm.templates import DEFAULTS

    store = store_for(DEFAULTS)
    await store.refresh()
    return store.pinned()


def question_prompt(summary: str, understanding: str, round_name: str, *,
                    include_context: bool = True) -> str:
    body = _render(templates.QUESTIONS, {
        "round_name": round_name,
        "focus": ROUND_FOCUS.get(round_name, round_name),
        "round_prefix": ROUND_PREFIX[round_name],
        "understanding": understanding or "(none)",
    })
    return f"{body}\n\n{pack_block(summary)}" if include_context else body


def brief_prompt(plan: TestPlan, summary: str, open_questions: list[str], *,
                 include_context: bool = True) -> str:
    body = _render(templates.BRIEF, {
        "confidence": plan.confidence,
        "methodology": ", ".join(plan.methodology),
        "test_design": ", ".join(plan.test_design) or "(default per behaviour)",
        "kinds": ", ".join(effective_kinds(plan)),
        "scope": ", ".join(plan.scope) or "(none)",
        "out_of_scope": ", ".join(plan.out_of_scope) or "(none)",
        "metrics": ", ".join(plan.metrics) or "(none)",
        "open_questions": "\n".join(f"- {q}" for q in open_questions) or "(none)",
    })
    return f"{body}\n\n{pack_block(summary)}" if include_context else body


def scope_classify_prompt(plan: TestPlan, summary: str, grounded, understanding: str = "") -> str:
    """One-call SCOPE CLASSIFIER: pick the pack node ids that are IN scope for testing THIS ticket.
    The crawl sweeps in sibling tickets, framework/meta pages and cross-project docs; those are context,
    not things to write scenarios for. Marker 'SCOPE CLASSIFIER' (not a generator router substring).
    The confirmed ``understanding`` is the ANCHOR — the model classifies each node against the feature
    it describes, not against the run id (which carries no signal).

    ``summary`` is NOT re-embedded here: ``classify_in_scope`` already passes the same pack as the
    agent's cached system instruction, so inlining it again sent the whole pack twice in one call —
    the second copy uncached, and pure waste. The parameter stays (callers and the stored template
    both still name it) but renders empty."""
    listing = "\n".join(
        f"- {n.id} :: {n.title} :: {(n.synopsis or '')[:160]}" for n in grounded) or "(none)"
    target = understanding.strip() or (
        f"(no understanding text; anchor on these in-scope hints: {', '.join(plan.scope) or '(none)'})")
    return _render(templates.SCOPE_CLASSIFY, {
        "target": target,
        "scope_hints": ", ".join(plan.scope) or "(none)",
        "out_hints": ", ".join(plan.out_of_scope) or "(none)",
        "listing": listing,
        "pack": "",  # the pack rides in the cached system instruction — see the docstring
    })


def _scope_block(plan: TestPlan) -> str:
    """The confirmed In/Out-of-scope boundary, injected into every generator AND the judge. The pack
    often carries sibling/framework nodes the KGA crawl swept in but the plan ruled OUT; the pack alone
    doesn't say what's out of bounds, so name it explicitly — else the model (and the judge) treat an
    out-of-scope sibling scenario the same as an in-scope one, tanking faithfulness + scope precision."""
    return (
        f"In scope (cover ONLY these behaviours): {', '.join(plan.scope) or '(the pack)'}.\n"
        f"Out of scope (do NOT cover these — sibling tickets, framework/meta pages): "
        f"{', '.join(plan.out_of_scope) or '(none)'}.\n"
    )


def _plan_params(plan: TestPlan) -> dict:
    """The parameters every generator template shares."""
    return {
        "methodology": ", ".join(plan.methodology),
        "metrics": ", ".join(plan.metrics),
        "methods": ", ".join(plan.test_design) or "standard technique per behaviour",
        "kinds": ", ".join(effective_kinds(plan)),
        "scope_block": _scope_block(plan),
        "context_id": plan.context_id,
    }


def scenarios_prompt(plan: TestPlan, summary: str, test_data: list[TestData],
                     reflections: list[str] | None = None, *, include_context: bool = True,
                     focus_units: list[str] | None = None,
                     crosscutting_kinds: list[str] | None = None) -> str:
    # A "generate the whole uncapped suite in ONE call" ask overruns the model's max output on a rich
    # pack -> the JSON array truncates -> schema-invalid -> silent heuristic fallback. The caller
    # batches the pack's units and passes one batch here per call; `focus_units` scopes THIS call's
    # output to a handful of ids so the array always fits. The full pack rides in the cached prefix.
    # `crosscutting_kinds` is the ORTHOGONAL axis: security/i18n/concurrency/performance apply to the
    # feature as a whole, not one pack node, so the per-node batches never emit them — this variant asks
    # for one scenario per distinct risk NAMED in the test-design methods, across those kinds only.
    focus = ""
    if crosscutting_kinds:
        focus = ("\nGENERATE ONLY cross-cutting scenarios for these kinds: "
                 f"{', '.join(crosscutting_kinds)}. They apply to the WHOLE feature, not a single pack "
                 "unit — cover EACH distinct risk named in the test-design methods above (e.g. every "
                 "listed security / encoding / concurrency / performance case: zip-slip, zip bomb, deep "
                 "nesting, symlink, duplicate entries, CP437-vs-UTF-8, NFC-vs-NFD, pool-size-N, size "
                 "boundaries, …), ONE scenario per distinct risk. Do NOT emit plain happy / negative / "
                 "boundary / error cases here — those are generated separately.\n")
    elif focus_units:
        focus = ("\nGENERATE ONLY for these pack unit ids — one scenario per applicable kind for EACH, "
                 "and NONE for any id not listed here (the rest of the pack is context to draw on, not "
                 f"to cover in this call):\n{', '.join(focus_units)}\n")
    body = _render(templates.SCENARIOS, {
        **_plan_params(plan),
        "data_ids": ", ".join(d.id for d in test_data) or "(none)",
        "gherkin": GHERKIN_GUIDELINES,
        "pack_grounding": PACK_GROUNDING,
        "focus": focus,
        "revision": revision_feedback(reflections),
    })
    return f"{body}\n{pack_block(summary)}" if include_context else body


def testdata_prompt(plan: TestPlan, summary: str, *, include_context: bool = True) -> str:
    body = _render(templates.TESTDATA, _plan_params(plan))
    return f"{body}\n\n{pack_block(summary)}" if include_context else body


def judge_scenarios_prompt(plan: TestPlan, summary: str, scenarios: list[TestScenario], *,
                           include_context: bool = True) -> str:
    """The P4 LLM-as-judge rubric (§3.4). Deliberately avoids the 'TEST SCENARIOS'/'TEST DATA'/
    'STEP-BY-STEP' substrings the generator router keys on — its marker is 'QA CRITIC'."""
    listing = "\n".join(
        f"- {s.id} [{s.kind}] {s.title} :: {s.description} (cites: {', '.join(s.source_refs) or 'NOTHING'})"
        for s in scenarios) or "(none generated)"
    body = _render(templates.JUDGE_SCENARIOS, {**_plan_params(plan), "listing": listing})
    return f"{body}\n\n{pack_block(summary)}" if include_context else body


def steps_prompt(scenarios: list[TestScenario], plan: TestPlan, summary: str,
                 test_data: list[TestData], *, include_context: bool = True) -> str:
    # Give the step-writer each scenario's OWN description (the Then it must assert), preconditions
    # (the Given to arrange) and data_refs (which data THIS scenario uses) — not just id/kind/title,
    # else it writes generic steps unanchored to what the scenario actually verifies.
    def _line(s: TestScenario) -> str:
        pre = "; ".join(s.preconditions) or "—"
        data = ", ".join(s.data_refs) or "—"
        return f"- {s.id} [{s.kind}] {s.title} :: verifies: {s.description or '—'} | given: {pre} | data: {data}"

    body = _render(templates.STEPS, {
        **_plan_params(plan),
        "data_ids": ", ".join(d.id for d in test_data) or "(none)",
        "gherkin": GHERKIN_GUIDELINES,
        "listing": "\n".join(_line(s) for s in scenarios),
    })
    return f"{body}\n\n{pack_block(summary)}" if include_context else body
