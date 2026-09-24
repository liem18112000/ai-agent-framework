"""Test Executor prompt BODIES, as addressable store-backed templates.

Same split as the other registries (``common/bridge/prompts``, ``common/testplan/llm/templates``): the
LOGIC stays in Python (the JEV cascade + heuristic fallback in ``runner.triage``) and only the TEXT
lives here, editable/versioned through the DB prompt store. ``exec.triage`` is the instruction the JEV
``DecisionProvider`` classifies a failure with (Bug/Heal/Flaky/Environment) — freeform prose, no JSON
output contract, so no ``contract``/``forbids``. Offline / no DB → the body below is the fallback.
"""

from __future__ import annotations

from common.prompts import NONE, PromptTemplate, declared_vars, store_for

EXEC_TRIAGE = "exec.triage"   # the JEV failure-classifier instruction


_TRIAGE_BODY = (
    "Classify this test failure into exactly one bucket: Bug (a real product defect), Heal (a UI/"
    "selector change the test should adapt to), Flaky (non-deterministic, not a real failure), or "
    "Environment (infrastructure / connectivity / auth, not the code under test)."
)


def _t(key: str, body: str) -> PromptTemplate:
    """Freeform instruction template: params auto-derived, no output contract to enforce."""
    return PromptTemplate(key=key, body=body, version=0, engine=NONE, required_vars=declared_vars(body))


#: version 0 = the body compiled into the image; DB-published versions start at 1.
DEFAULTS = {t.key: t for t in (
    _t(EXEC_TRIAGE, _TRIAGE_BODY),
)}


def triage_instructions() -> str:
    """The JEV triage classifier instruction — the DB-published body when a DB is configured, else the
    compiled default. Read fresh per call so a publish takes effect without a redeploy."""
    return store_for(DEFAULTS).get(EXEC_TRIAGE).render()
