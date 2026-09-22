"""P6 — the engine-path prompt bodies (interrogation questions + understanding brief) as templates.

These are the ``complete()`` (non-ADK) prompts used by the KGA interrogation rounds. The per-round
GUIDANCE text stays a Python constant in ``prompts.py`` and is injected as ``$guidance``: it is
round-selection logic, and §8's split holds — logic in Python, text in the store.
"""

from __future__ import annotations

from common.prompts import NONE, PromptTemplate, declared_vars

QUESTIONS = "engine.questions"
UNDERSTANDING = "engine.understanding"

_QUESTIONS_BODY = """You are the QA Testing Agent's interrogation step, applying the vinnstack interrogation method for this round.

$guidance

Output rules:
- Self-answer anything derivable from the pack, marking status 'self-answered' with your recommendation as the answer. Surface as 'open' the genuine judgement calls — where two valid choices change what gets built or verified. A round with no open questions is a real outcome, not a target.
- Every open question needs 2-4 options (label + implication), a recommendation + rationale, and depends_on (ids of earlier questions it is gated on); order by dependency.

Return ONLY a JSON array; each item: {id, round, question, why, options:[{label,implication}], recommendation, depends_on:[], applies_to, status, confidence}. Use id prefix 'Q-$round_prefix-'.$ctx"""

_UNDERSTANDING_BODY = """Restate, in plain language for a human to confirm, what the QA Testing Agent now understands. Overall confidence is '$confidence'. Use these headings: Problem, In scope, Out/deferred, Settled decisions, Open gaps.

Context pack:
$pack

Settled decisions:
$decided

Deferred (out of scope for now):
$deferred

Open gaps:
$opens
"""


def _t(key: str, body: str) -> PromptTemplate:
    # engine.questions is parsed by `loads_array`, so the ARRAY wording is REQUIRED here — the exact
    # inverse of the testplan generators. The contract is per key, never global.
    contract = ("Return ONLY a JSON array",) if key == QUESTIONS else ()
    return PromptTemplate(key=key, body=body, version=0, engine=NONE,
                          required_vars=declared_vars(body), contract=contract)


DEFAULTS = {t.key: t for t in (
    _t(QUESTIONS, _QUESTIONS_BODY),
    _t(UNDERSTANDING, _UNDERSTANDING_BODY),
)}

#: ``engine.questions`` is consumed by ``loads_array`` (NOT a run_json_agent object wrapper), so a
#: bare JSON array is CORRECT here — the opposite of the testplan generators. Pinning it stops a
#: well-meaning publish from "fixing" it to an object and breaking the parser.
SCHEMA_CONTRACT = {
    QUESTIONS: "Return ONLY a JSON array",
}
