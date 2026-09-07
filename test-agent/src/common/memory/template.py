"""Markdown templates for the memory-bank artifacts (notes, index, run-logs, insights).

Separated from render.py so the document shapes can be edited as text. Filled with
``str.format`` — values are inserted literally, so braces inside a value (e.g. JSON params)
are safe. The frontmatter ``key: value`` lines are load-bearing: memory.serialize parses
them back, so keep those keys intact.
"""

from __future__ import annotations

NOTE_MD = """\
---
id: {id}
type: {type}
source_url: {source_url}
title: {title}
fetched_at: {fetched_at}
depth: {depth}
run_id: {run_id}
confidence: {confidence}
links_out: {links_out}
---

# {heading}

{synopsis}

## Links

| url | type | origin | in_scope |
| --- | --- | --- | --- |
{link_rows}
"""

INDEX_MD = """\
# Knowledge index

{summary}

| id | type | title |
| --- | --- | --- |
{rows}
"""

RUN_LOG_MD = """\
# Run {run_id}

- seed: {seed}
- params: {params}
- nodes_fetched: {nodes_fetched}
- links_found: {links_found}
- confidence: {confidence}
- started: {started}
- ended: {ended}

## Sources

{sources}
"""

INSIGHT_MD = """\
---
id: {id}
kind: {kind}
context_id: {context_id}
question_id: {question_id}
answered_by: {answered_by}
confidence: {confidence}
source_refs: {source_refs}
created_at: {created_at}
run_id: {run_id}
---

# {statement}
"""

REFINE_RUN_LOG_MD = """\
# Refine run {run_id}

- context_id: {context_id}
- seed: {seed}
- rounds: {rounds}
- questions_raised: {questions_raised}
- questions_answered: {questions_answered}
- insights_written: {insights_written}
- understanding_confidence: {understanding_confidence}
- started: {started}
- ended: {ended}
"""
