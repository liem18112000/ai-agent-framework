"""Store-backed prompt bodies for the executor — the JEV triage classifier instruction (`exec.triage`).

Same split as the sibling registries: LOGIC stays in Python, only the editable/versioned TEXT lives here.
"""

from __future__ import annotations

from test_executor.prompts.registry import DEFAULTS, EXEC_TRIAGE, triage_instructions

__all__ = ["DEFAULTS", "EXEC_TRIAGE", "triage_instructions"]
