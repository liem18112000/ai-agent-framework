"""Markdown templates for the Test-Plan memory-bank artifacts (plan, run-log).

Separated from render.py so the document shapes can be edited as text (mirrors
common.memory.template). Filled with ``str.format``; the bullet-list bodies are
pre-rendered by render.py and inserted literally. These are write-only/presentational —
read-back always goes through the JSON sidecar, never this markdown.
"""

from __future__ import annotations

PLAN_MD = """\
# Test Plan — {context_id} (status: {status}, confidence: {confidence})

## Methodology
{methodology}

## Scope
{scope}

## Out of scope
{out_of_scope}

## Metrics — what 'passed' means
{metrics}

## Built on
{source_refs}
"""

PLAN_RUN_LOG_MD = """\
# Plan run {run_id} — {context_id}

- plan: {plan_id}
- rounds: {rounds}
- questions raised/answered: {questions_raised}/{questions_answered}
- decisions: {decisions_written}
- scenarios/steps/test-data: {scenarios_written}/{steps_written}/{testdata_written}
- confidence: {confidence}
- gaps: {gaps}
- started/ended: {started} / {ended}
"""

SCENARIOS_MD = """\
# Test Scenarios — {context_id}

{body}
"""
