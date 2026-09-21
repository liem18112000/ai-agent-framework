"""The bridge/gateway prompt BODIES, as addressable templates (freeform instruction text).

Same split as the other registries (``common/testplan/llm/templates``, the KGA planners): the LOGIC
stays in Python — ``test_prompt`` still computes the JIRA-key fallback — and only the TEXT lives here,
editable/versioned through the prompt store. These three are FREEFORM instruction prose (like
``tpd.report`` / ``kga.report``): no JSON output contract, so no ``contract``/``forbids`` are attached.

Placeholders are ``$name`` (``string.Template``), never ``{name}`` — consistent with the store.
"""

from __future__ import annotations

from common.prompts import NONE, PromptTemplate, declared_vars, store_for

INSTRUCTIONS_KEY = "bridge.instructions"   # the gateway's own server instructions
TRIGGER = "bridge.trigger"                 # the shared TESTING-AGENT TRIGGER block
TEST_PROMPT = "bridge.test_prompt"         # body of the `test` MCP prompt ($key, $depth)


_INSTRUCTIONS_BODY = (
    "Single MCP gateway for the Testing Agent — ONE endpoint fronting three A2A agents "
    "(knowledge-gathering, test-plan-definition, test-evaluation). Pipeline: gather_knowledge -> "
    "refine -> approve -> [evaluate_pack] -> define_plan -> approve_plan -> implement_plan -> "
    "get_scenarios -> [evaluate_plan]. BENCHMARK group (read-only, over past runs): benchmark_run "
    "(one run's cached PQS/TPS scorecard — computed & saved if missing; auto-computed when a run "
    "finishes), compare_benchmarks (2+ runs side by side), summarize_benchmarks (the K<10 latest). "
    "Reuse the one context_id gather_knowledge returns for every "
    "later call. YOU (the client) own the confirm gates: before starting refine, approve, "
    "define_plan, approve_plan, and implement_plan, ask the user Yes/No yourself and call the tool "
    "only on yes. evaluate_pack / evaluate_plan are read-only quality gates and never block. "
    "implement_plan is MULTI-TURN (chunked to stay under the idle timeout): if its reply starts "
    "'[state: in_progress]', call implement_plan(context_id) again — no new args — until "
    "'[state: done]', then get_scenarios. "
    "ADMIN / utility group (list_runs, get_run, compare_runs, view_memory, backup_memory, "
    "list_backups, wipe_all) "
    "is an operator surface, NOT part of gather -> ... -> implement — never call it as a pipeline "
    "step. wipe_all is DESTRUCTIVE and needs a confirm token (the GCS bucket name, or 'WIPE' when "
    "unset); ask the user Yes/No first, same client-owned-gate convention as the pipeline."
)


_TRIGGER_BODY = (
    "TESTING-AGENT TRIGGER — when the user asks to test a Jira ticket (e.g. says "
    "'test LUZ-158390', 'test the ticket LUZ-158390', or invokes the `test` prompt), run the "
    "FULL Testing-Agent pipeline for that ticket, interactively. This spans the MCP servers "
    "`knowledge-gathering` and `test-plan-definition` (both required), plus the OPTIONAL "
    "`test-evaluation` scorer. Pipeline: "
    "gather_knowledge -> refine (ask the user each question round) -> approve -> "
    "[evaluate_pack — optional pack-quality gate] -> [knowledge report -> optional HTML artifact] -> define_plan "
    "(ask the user each methodology/scope/metrics round) -> approve_plan -> implement_plan -> "
    "get_scenarios -> build the ENRICHED HTML report (always). Reuse the one context_id gather_knowledge returns for "
    "every later call. OPTIONAL QUALITY GATE — if `test-evaluation` is connected, after approve "
    "call evaluate_pack(context_id): it scores the gathered+refined pack into a Pack Quality Score "
    "(retrieval recall/precision with a hard-negative leak gate + groundedness rubrics). If it "
    "flags a leak or low recall, surface that and offer to re-gather (exclude=... / repo=...) "
    "before planning; otherwise proceed. It is read-only and never blocks. YOU "
    "(the client) own the confirm gates: before each of starting refine, approve, starting "
    "define_plan, approve_plan, and implement_plan, ask the user a Yes/No YOURSELF via the "
    "client's interactive question/dialog UI and call the tool only once they say yes — never "
    "auto-approve. (The tools no longer prompt on their own: server-driven MCP elicitation was "
    "removed because Claude Code cannot deliver it over the bridges' remote HTTP transport, "
    "issue #85442.) For the per-round questions each interrogation returns, present them (options "
    "+ recommendation) and let the user pick before you submit the next answer. If the "
    "test-plan-definition tools are not connected, run gather+refine+approve and tell the user to "
    "connect that server before the plan stage. "
    "OPTIMIZE READS (fan-out) — the gated stages above are sequential (one context_id, a human "
    "gate before each), but the READ-ONLY steps are not: whenever you must read MANY Memory-Bank "
    "nodes at once (e.g. get_note across a large pack, or a search_memory / get_understanding "
    "sweep), run them in PARALLEL via concurrent read-only subagents — split the node ids into "
    "slices (~5 each), have each subagent fetch its slice and return compact per-node summaries "
    "(never full note bodies). This cuts wall-clock versus serial get_note round-trips and keeps "
    "large note bodies out of the driver's context. Never parallelize the stateful gated stages "
    "(refine / approve / define_plan / approve_plan / implement) or two ops on the same context_id."
)


_TEST_PROMPT_BODY = (
    "Run the **Testing Agent** end-to-end for Jira ticket **$key** (crawl depth $depth).\n\n"
    "Drive the whole KNOWLEDGE -> PLAN pipeline INTERACTIVELY over the two agents' MCP tools. "
    "At every question round and before every approve gate, show the user the questions (each "
    "option with its implication + the agent's recommendation) and WAIT for their answer — "
    "never auto-answer, never auto-approve. Reuse the one context_id from step 1 throughout. "
    "When a step needs to read many Memory-Bank nodes at once (e.g. summarizing the gathered "
    "pack, or a get_note sweep), FAN the reads out across concurrent read-only subagents (~5 "
    "nodes each, compact summaries) to save wall-clock + driver context; keep the gated stages "
    "sequential.\n\n"
    "Tools:\n"
    "- knowledge-gathering: gather_knowledge, refine, get_questions, get_understanding, approve\n"
    "- test-plan-definition: define_plan, get_plan, approve_plan, implement_plan, get_scenarios\n"
    "- test-evaluation (optional): evaluate_pack\n"
    "If the test-plan-definition tools are unavailable, run steps 1-3 and tell the user to "
    "connect that MCP server before continuing.\n\n"
    "1. Gather — gather_knowledge(seed=\"$key\", depth=$depth); capture the context_id; "
    "summarize nodes / links / declared gaps.\n"
    "2. Refine (interactive) — refine(context_id); for each round, show the questions + "
    "recommendations, ask the user, then refine(context_id, answer=\"Q-...: <choice>\"); repeat "
    "until 'Refinement complete'; show get_understanding(context_id) and ask the user to confirm.\n"
    "2b. Knowledge review (optional, interactive) — AFTER refinement and BEFORE approve: ASK the "
    "user Yes/No whether to review the gathered knowledge first. On YES, RENDER it yourself (see "
    "'Rendering artifacts' below) from the FULL data — get_understanding (understanding & summary), "
    "get_questions (open + answered), search_memory / get_note (every gathered source: jira / "
    "confluence / code / attachment, each with title + link), the declared gaps, and the Pack "
    "Quality Score if evaluate_pack has run. Read-only review to help the user decide — it never "
    "approves; the user still decides. On NO, continue to step 3.\n"
    "3. Approve (knowledge) — after the user confirms: approve(context_id).\n"
    "3b. Evaluate (optional) — if the test-evaluation server is connected: "
    "evaluate_pack(context_id); surface the Pack Quality Score + the retrieval/rubric "
    "breakdown. If it flags a bleed (leaked hard-negatives) or low recall, offer to re-gather "
    "(exclude=... / repo=...) before planning. Read-only; never blocks.\n"
    "3c. Knowledge review, final (optional, interactive) — at the END of the knowledge phase (after "
    "approve, and evaluate_pack if it ran), ASK the user Yes/No whether to see the knowledge review "
    "again, now WITH the Pack Quality Score + its component rubric (retrieval recall/precision, the "
    "hard-negative leak gate, the groundedness rubrics) populated. Same data + rendering as step 2b. "
    "Read-only; on NO, continue to step 4.\n"
    "4. Define (interactive)— define_plan(context_id); for each methodology/scope/metrics "
    "round, show the questions + recommendations, ask the user, then "
    "define_plan(context_id, answer=\"Q-...: <choice>\"); repeat until 'Plan definition "
    "complete'; show get_plan(context_id) and ask the user to confirm.\n"
    "4b. Plan review (optional, interactive) — AFTER define and BEFORE approve_plan: ASK the "
    "user Yes/No whether to review the defined plan first. On YES, RENDER it yourself (see "
    "'Rendering artifacts') from the FULL data — get_plan (methodology, test-design techniques, "
    "in-scope, out-of-scope, metrics / what \"passed\" means, confidence), every confirmed decision "
    "per round (statement, chosen, rationale, rejected options, provenance), and get_questions for "
    "anything still open. No scenarios yet — those come after approval. Read-only review; the user "
    "still decides. On NO, continue to step 5.\n"
    "5. Approve (plan) — after the user confirms: approve_plan(context_id).\n"
    "6. Implement — implement_plan(context_id), then get_scenarios(context_id); report the test "
    "data, happy/negative scenarios, steps, and the exported .feature.\n"
    "7. Final test plan (interactive) — on success of get_scenarios, RENDER the full test plan "
    "yourself (see 'Rendering artifacts') from the FULL data — get_plan + its decisions (methodology, "
    "test-design, scope in/out, metrics), get_scenarios (EVERY scenario: title, kind, methodology, "
    "ordered steps with action -> expected/oracle, data-refs), ALL test-data fixtures, get_coverage "
    "(requirement x kind matrix + traceability + gaps), and the PQS/TPS component breakdown if "
    "evaluate_plan / benchmark_run has run, plus the exported .feature. Include the FULL information "
    "for every scenario — never downgrade to a bare title list.\n"
    "8. Summarize — the context_id, the confirmed plan, and where the run lives in the Memory Bank.\n"
    "\n"
    "Rendering artifacts (steps 2b / 3c / 4b / 7): the agents STORE the full run and return it via the "
    "get_* tools above — they do NOT emit HTML. YOU (the client) render. First assemble the full data "
    "for that artifact kind, then render it with an appropriate client rendering skill. If you have no "
    "suitable rendering skill available, ASK THE USER how they want it presented (e.g. an HTML "
    "artifact, a Claude Doc, or Markdown) and render in that form. Whatever the format, it MUST carry "
    "the FULL information listed for that artifact kind above — a review/plan is a complete document, "
    "not a summary. If you recorded a published URL, register it with record_artifact(context_id, "
    "kind, url) so it is retrievable later via get_run.\n"
)


def _t(key: str, body: str) -> PromptTemplate:
    """Freeform instruction template: params auto-derived, no output contract to enforce."""
    return PromptTemplate(key=key, body=body, version=0, engine=NONE,
                          required_vars=declared_vars(body))


#: version 0 everywhere — the body compiled into the image. DB-published versions start at 1.
DEFAULTS = {t.key: t for t in (
    _t(INSTRUCTIONS_KEY, _INSTRUCTIONS_BODY),
    _t(TRIGGER, _TRIGGER_BODY),
    _t(TEST_PROMPT, _TEST_PROMPT_BODY),
)}


def server_instructions() -> str:
    """The gateway's own MCP server instructions (stored body, no params)."""
    return store_for(DEFAULTS).get(INSTRUCTIONS_KEY).render()


def trigger_instructions() -> str:
    """The shared TESTING-AGENT TRIGGER block delivered by the server (stored body, no params)."""
    return store_for(DEFAULTS).get(TRIGGER).render()


def test_prompt(jira_key: str = "", depth: str = "2") -> str:
    """Body of the `test` MCP prompt — the full interactive workflow for one ticket.

    The JIRA-key fallback is computed HERE (logic in Python); only the text lives in the store."""
    key = jira_key.strip() or "<JIRA-KEY the user names>"
    return store_for(DEFAULTS).get(TEST_PROMPT).render({"key": key, "depth": depth})
