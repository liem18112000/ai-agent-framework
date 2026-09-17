"""P1 — the testplan prompt BODIES, as addressable templates.

The split is deliberate: **logic stays in Python, text moves to the store.** ``prompts.py`` still
computes every parameter (which kinds are effective, what the scope block says, how the scenario
listing is formatted); this module holds only the skeleton those parameters drop into. That keeps the
editable surface exactly the part that has been wrong three times this week — the wording — without
putting control flow in a database row.

Placeholders are ``$name`` (``string.Template``), never ``{name}``: these bodies are full of literal
braces (``{"items": [ ... ]}``, ``{id, title, kind…}``) that must reach the model untouched.
"""

from __future__ import annotations

from common.prompts import NONE, PromptTemplate

QUESTIONS = "tpd.questions"
BRIEF = "tpd.brief"
SCOPE_CLASSIFY = "tpd.scope_classify"
SCENARIOS = "tpd.scenarios"
TESTDATA = "tpd.testdata"
JUDGE_SCENARIOS = "tpd.judge_scenarios"
STEPS = "tpd.steps"

_QUESTIONS_BODY = """You are the QA Testing Agent DEFINING A TEST PLAN, running the '$round_name' round.
Focus: $focus

Rules:
- Don't ask what the confirmed understanding + pack already settle — self-answer it (status 'self-answered') with your recommendation as the answer.
- Surface (status 'open') ONLY genuine judgement calls where two valid choices change what gets tested or how 'passed' is judged.
- Every question needs 2-4 options (label + implication), a recommendation, and depends_on (ids of earlier questions it is gated on).

Return ONLY a JSON array; each item: {id, round, question, why, options:[{label,implication}], recommendation, depends_on:[], applies_to, status, confidence}. Use id prefix 'Q-$round_prefix-'.

Confirmed understanding:
$understanding"""

_BRIEF_BODY = """Restate, in plain language for a human to confirm, the Test Plan the QA Testing Agent now proposes. Overall confidence is '$confidence'. Use these headings: Methodology, Test-design method, In scope, Out of scope, Passed means, Open questions.

Methodology: $methodology
Test-design method: $test_design
Test kinds: $kinds
In scope: $scope
Out of scope: $out_of_scope
Passed means: $metrics
Open questions:
$open_questions"""

_SCOPE_CLASSIFY_BODY = """You are a SCOPE CLASSIFIER for a QA test plan.

=== TICKET UNDER TEST (the ONLY feature in scope) ===
$target
=== END TICKET UNDER TEST ===

From the pack nodes below, return ONLY the ids that DIRECTLY implement, specify, or exercise the feature described above — the ticket's own code, requirements, specs and spec attachments.
The pack was CRAWLED FROM AN EPIC and deliberately contains MANY sibling Jira tickets that are DIFFERENT issues from the one under test. EXCLUDE them ALL. Also exclude framework/meta/agent-infrastructure pages and cross-project documentation. A node is IN only if you can state, in one phrase, how it belongs to THE feature above; if it is about a different ticket or feature — even a related-looking one in the same epic — leave it OUT.
In-scope hints: $scope_hints. Out-of-scope hints: $out_hints.

Return ONLY a JSON object {in_scope_ids: [pack ids, verbatim]} — a SUBSET of the ids below. Be selective: expect to keep only a HANDFUL (the target ticket + its implementing code/specs), not most of the list. Never return an empty list — if unsure keep only the node(s) MOST specific to the feature above.

Pack nodes:
$listing

$pack"""

_SCENARIOS_BODY = """You are the QA Testing Agent generating TEST SCENARIOS from a confirmed plan.
Methodology: $methodology. Pass metric(s): $metrics.
Test-design method(s) to apply: $methods.
Kinds to cover (open set — cover every one that applies): $kinds.
Available test-data ids (use in data_refs): $data_ids.
$scope_block
$gherkin$pack_grounding
Rules:
- For EACH IN-SCOPE acceptance criterion / behaviour in the pack, generate a scenario for EACH listed kind that applies (skip a kind only when genuinely inapplicable to that behaviour). Emit as MANY cases per kind as the test-design method yields — there is NO cap; aim to cover 100%.
- Do NOT invent scenarios for pack nodes that are out-of-scope, sibling tickets, or framework/meta pages — cover the ticket's own behaviours only.
- Each scenario MUST cite the REAL note/insight id it covers in source_refs (a pack id, verbatim).
$focus
Return ONLY a JSON object {"items": [ ... ]} — each item: {id, title, kind, methodology, description (one sentence: what it verifies), rationale (why it matters), preconditions:[], data_refs:[], source_refs:[]}. Use id prefix 'scenario:$context_id:'.
$revision"""

_TESTDATA_BODY = """You are the QA Testing Agent generating TEST DATA for a confirmed plan.
Methodology: $methodology. Pass metric(s): $metrics.
Test-design method(s): $methods.
Kinds the data must support (include negative/boundary/error variants): $kinds.
$scope_block
Produce the data the scenarios need: at least one test-account (authenticated caller, with role / tenant / permissions matched to the stories) and one mock-data record per key IN-SCOPE entity / behaviour in the pack, each with CONCRETE realistic fields grounded in the pack (not placeholders). Per the test-design method, include boundary/invalid values (e.g. at/over each documented limit) so the negative/boundary/error scenarios have data. Add a fixture for any input payload the API needs.

Return ONLY a JSON object {"items": [ ... ]} — each item: {id, kind (mock-data|test-account|fixture), spec (object of concrete fields), source_refs:[note ids]}. Use id prefix 'test-data:$context_id:'."""

_JUDGE_BODY = """You are a STRICT, INDEPENDENT QA CRITIC. SCORE THE SCENARIOS below against the approved plan + context pack. You did not write them — reward real coverage, punish invention.
Methodology: $methodology. Pass metric(s): $metrics.
Test-design method(s): $methods.
Kinds that should be covered (open set): $kinds.
$scope_block
Score EACH dimension 0.0–1.0 (1.0 = excellent):
- ac_coverage: every IN-SCOPE acceptance criterion / behaviour has a scenario (do NOT count out-of-scope sibling nodes as missing coverage).
- atomicity: one behaviour per scenario, independently runnable.
- testability: a concrete, observable Then outcome (not 'it works').
- traceability: each scenario cites a REAL note/insight id from the pack.
- faithfulness: NOTHING invented, AND nothing generated for an OUT-OF-SCOPE node — a scenario covering a sibling/framework node the plan ruled out is an invention; penalise it here.
- negative_edge_coverage: the risky behaviours have the applicable kinds above (not just negative/boundary/error — include any elicited extras like security/performance/concurrency).
- non_duplication: 1.0 = no near-duplicate scenarios.

List concrete 'issues' (what is wrong, citing scenario ids) and 'reflections' — imperative one-line fixes the generator should apply on its next attempt. Set 'overall' to your holistic 0–1 score and 'accept' true only if this suite is ready for a human to approve.

Return ONLY a JSON object: {overall, ac_coverage, atomicity, testability, traceability, faithfulness, negative_edge_coverage, non_duplication, accept (bool), issues:[], reflections:[]}.

Scenarios under review:
$listing"""

_STEPS_BODY = """You are the QA Testing Agent writing STEP-BY-STEP steps for each scenario.
Methodology: $methodology. Pass metric(s): $metrics.
Test-data ids (reference these in the Given step): $data_ids.

$gherkin
For EVERY scenario below write concrete Given/When/Then steps (3-5 each): arrange the preconditions + data, perform the API action, assert the response status, then assert the end state / pass metric. negative -> assert rejection + no side effects; boundary -> assert behaviour at the limit; error -> assert graceful failure + consistent state.

Scenarios:
$listing

Return ONLY a JSON object {"items": [ ... ]} — each item: {scenario_id, steps:[{order, keyword (Given|When|Then|And), action, expected}]}."""


#: P5.1 — the output contract enforced at the WRITE boundary: (required substrings, forbidden ones).
#: The ADK ``output_schema`` for these generators is an object wrapper, so a body asking for a bare
#: array parses to a single element and the batch silently degrades — the defect that cost three
#: rebuilds. Pinning it here means `prompt_publish` rejects it, not a 15-minute redeploy.
_CONTRACTS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    SCENARIOS: (('{"items": [ ... ]}',), ("Return ONLY a JSON array",)),
    TESTDATA: (('{"items": [ ... ]}',), ("Return ONLY a JSON array",)),
    STEPS: (('{"items": [ ... ]}',), ("Return ONLY a JSON array",)),
    JUDGE_SCENARIOS: (("Return ONLY a JSON object",), ()),
    SCOPE_CLASSIFY: (("Return ONLY a JSON object",), ()),
}


def _t(key: str, body: str) -> PromptTemplate:
    from common.prompts import declared_vars

    contract, forbids = _CONTRACTS.get(key, ((), ()))
    return PromptTemplate(key=key, body=body, version=0, engine=NONE,
                          required_vars=declared_vars(body),
                          contract=contract, forbids=forbids)


#: version 0 everywhere — the body compiled into the image. DB-published versions start at 1.
DEFAULTS = {t.key: t for t in (
    _t(QUESTIONS, _QUESTIONS_BODY),
    _t(BRIEF, _BRIEF_BODY),
    _t(SCOPE_CLASSIFY, _SCOPE_CLASSIFY_BODY),
    _t(SCENARIOS, _SCENARIOS_BODY),
    _t(TESTDATA, _TESTDATA_BODY),
    _t(JUDGE_SCENARIOS, _JUDGE_BODY),
    _t(STEPS, _STEPS_BODY),
)}

#: Derived view kept for readability/tests — the single source of truth is ``_CONTRACTS`` above.
SCHEMA_CONTRACT = {k: req[0] for k, (req, _f) in _CONTRACTS.items() if req}
