"""Prompt templates for the Claude-on-Vertex plan generators."""

from __future__ import annotations

from common.testplan.models import ROUND_PREFIX, TestData, TestPlan, TestScenario

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
}


# P0 — Gherkin best-practice grounding injected into the scenario/steps generators. Declarative,
# one-behaviour-per-scenario, business language, independent scenarios, concrete data (no glue).
GHERKIN_GUIDELINES = (
    "Gherkin best practices (follow all):\n"
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


def question_prompt(summary: str, understanding: str, round_name: str) -> str:
    return (
        f"You are the QA Testing Agent DEFINING A TEST PLAN, running the '{round_name}' round.\n"
        f"Focus: {ROUND_FOCUS.get(round_name, round_name)}\n\n"
        "Rules:\n"
        "- Don't ask what the confirmed understanding + pack already settle — self-answer it "
        "(status 'self-answered') with your recommendation as the answer.\n"
        "- Surface (status 'open') ONLY genuine judgement calls where two valid choices change what "
        "gets tested or how 'passed' is judged.\n"
        "- Every question needs 2-4 options (label + implication), a recommendation, and depends_on "
        "(ids of earlier questions it is gated on).\n\n"
        "Return ONLY a JSON array; each item: {id, round, question, why, options:[{label,"
        "implication}], recommendation, depends_on:[], applies_to, status, confidence}. "
        f"Use id prefix 'Q-{ROUND_PREFIX[round_name]}-'.\n\n"
        f"Confirmed understanding:\n{understanding or '(none)'}\n\n"
        f"Context pack:\n{summary}"
    )


def brief_prompt(plan: TestPlan, summary: str, open_questions: list[str]) -> str:
    opens = "\n".join(f"- {q}" for q in open_questions) or "(none)"
    return (
        "Restate, in plain language for a human to confirm, the Test Plan the QA Testing Agent now "
        f"proposes. Overall confidence is '{plan.confidence}'. Use these headings: Methodology, "
        "In scope, Out of scope, Passed means, Open questions.\n\n"
        f"Methodology: {', '.join(plan.methodology)}\n"
        f"In scope: {', '.join(plan.scope) or '(none)'}\n"
        f"Out of scope: {', '.join(plan.out_of_scope) or '(none)'}\n"
        f"Passed means: {', '.join(plan.metrics) or '(none)'}\n"
        f"Open questions:\n{opens}\n\n"
        f"Context pack:\n{summary}"
    )


def scenarios_prompt(plan: TestPlan, summary: str, test_data: list[TestData],
                     reflections: list[str] | None = None) -> str:
    metrics = " ".join(plan.metrics).lower()
    happy_only = "happy only" in metrics or "happy-only" in metrics
    data_ids = ", ".join(d.id for d in test_data) or "(none)"
    return (
        "You are the QA Testing Agent generating TEST SCENARIOS from a confirmed plan.\n"
        f"Methodology: {', '.join(plan.methodology)}. Pass metric(s): {', '.join(plan.metrics)}.\n"
        f"Coverage: {'happy path only' if happy_only else 'happy + negative + boundary + error, per behaviour'}.\n"
        f"Available test-data ids (use in data_refs): {data_ids}.\n\n"
        + GHERKIN_GUIDELINES + PACK_GROUNDING + "\n"
        "Rules:\n"
        "- For EACH acceptance criterion / behaviour in the pack, generate a happy-path scenario"
        + ("" if happy_only else " AND a negative, a boundary, and an error scenario (4 kinds per "
           "behaviour); skip a kind only when it is genuinely inapplicable to that behaviour")
        + ".\n"
        "- Each scenario MUST cite the note/insight id it covers in source_refs.\n\n"
        "Return ONLY a JSON array; each item: {id, title, kind (happy|negative|boundary|error), "
        "methodology, description (one sentence: what it verifies), rationale (why it matters), "
        "preconditions:[], data_refs:[], source_refs:[]}. "
        f"Use id prefix 'scenario:{plan.context_id}:'.\n"
        + revision_feedback(reflections)
        + f"\nContext pack:\n{summary}"
    )


def testdata_prompt(plan: TestPlan, summary: str) -> str:
    return (
        "You are the QA Testing Agent generating TEST DATA for a confirmed plan.\n"
        f"Methodology: {', '.join(plan.methodology)}.\n"
        "Produce the data the scenarios need: at least one test-account (authenticated caller, "
        "with role / tenant / permissions matched to the stories) and one mock-data record per "
        "key entity / behaviour in the pack, each with CONCRETE realistic fields grounded in the "
        "pack (not placeholders). Add a fixture for any input payload the API needs.\n\n"
        "Return ONLY a JSON array; each item: {id, kind (mock-data|test-account|fixture), "
        "spec (object of concrete fields), source_refs:[note ids]}. "
        f"Use id prefix 'test-data:{plan.context_id}:'.\n\n"
        f"Context pack:\n{summary}"
    )


def judge_scenarios_prompt(plan: TestPlan, summary: str, scenarios: list[TestScenario]) -> str:
    """The P4 LLM-as-judge rubric (§3.4). Deliberately avoids the 'TEST SCENARIOS'/'TEST DATA'/
    'STEP-BY-STEP' substrings the generator router keys on — its marker is 'QA CRITIC'."""
    listing = "\n".join(
        f"- {s.id} [{s.kind}] {s.title} :: {s.description} (cites: {', '.join(s.source_refs) or 'NOTHING'})"
        for s in scenarios) or "(none generated)"
    return (
        "You are a STRICT, INDEPENDENT QA CRITIC. SCORE THE SCENARIOS below against the approved "
        "plan + context pack. You did not write them — reward real coverage, punish invention.\n"
        f"Methodology: {', '.join(plan.methodology)}. Pass metric(s): {', '.join(plan.metrics)}.\n\n"
        "Score EACH dimension 0.0–1.0 (1.0 = excellent):\n"
        "- ac_coverage: every acceptance criterion / behaviour in the pack has a scenario.\n"
        "- atomicity: one behaviour per scenario, independently runnable.\n"
        "- testability: a concrete, observable Then outcome (not 'it works').\n"
        "- traceability: each scenario cites a REAL note/insight id from the pack.\n"
        "- faithfulness: NOTHING invented — no requirement/endpoint/field/limit the pack lacks.\n"
        "- negative_edge_coverage: negative, boundary and error cases for the risky behaviours.\n"
        "- non_duplication: 1.0 = no near-duplicate scenarios.\n\n"
        "List concrete 'issues' (what is wrong, citing scenario ids) and 'reflections' — imperative "
        "one-line fixes the generator should apply on its next attempt. Set 'overall' to your "
        "holistic 0–1 score and 'accept' true only if this suite is ready for a human to approve.\n\n"
        "Return ONLY a JSON object: {overall, ac_coverage, atomicity, testability, traceability, "
        "faithfulness, negative_edge_coverage, non_duplication, accept (bool), issues:[], "
        "reflections:[]}.\n\n"
        f"Scenarios under review:\n{listing}\n\n"
        f"Approved plan + context pack:\n{summary}"
    )


def steps_prompt(scenarios: list[TestScenario], plan: TestPlan, summary: str,
                 test_data: list[TestData]) -> str:
    data_ids = ", ".join(d.id for d in test_data) or "(none)"
    listing = "\n".join(f"- {s.id} [{s.kind}] {s.title}" for s in scenarios)
    return (
        "You are the QA Testing Agent writing STEP-BY-STEP steps for each scenario.\n"
        f"Methodology: {', '.join(plan.methodology)}. Pass metric(s): {', '.join(plan.metrics)}.\n"
        f"Test-data ids (reference these in the Given step): {data_ids}.\n\n"
        + GHERKIN_GUIDELINES + "\n"
        "For EVERY scenario below write concrete Given/When/Then steps (3-5 each): arrange the "
        "preconditions + data, perform the API action, assert the response status, then assert "
        "the end state / pass metric. negative -> assert rejection + no side effects; boundary -> "
        "assert behaviour at the limit; error -> assert graceful failure + consistent state.\n\n"
        f"Scenarios:\n{listing}\n\n"
        "Return ONLY a JSON array; each item: {scenario_id, steps:[{order, "
        "keyword (Given|When|Then|And), action, expected}]}.\n\n"
        f"Context pack:\n{summary}"
    )
