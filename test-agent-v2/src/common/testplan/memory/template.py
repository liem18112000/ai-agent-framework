"""Markdown templates for the Test-Plan memory-bank artifacts (plan, run-log)."""

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
