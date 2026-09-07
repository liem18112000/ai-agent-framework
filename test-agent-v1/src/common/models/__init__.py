"""Data contracts for the Knowledge-Gathering agent (stdlib dataclasses).

Split into cohesive submodules — `refine` (question/answer/insight + refine constants),
`graph` (links/notes/run-log/index + link constants), `pack` (the grounded context pack),
and `bridge` (the normalized A2A reply) — and re-exported flat here so callers keep using
`from common.models import <name>` unchanged.
"""

from common.models.bridge import A2AResult
from common.models.graph import (
    ATTACHMENT,
    BITBUCKET,
    CODEGRAPH,
    CONFLUENCE_PAGE,
    EXTERNAL_WEB,
    FIGMA,
    GOOGLE_DOC,
    JIRA_ISSUE,
    Graph,
    LinkRecord,
    Note,
    RunLog,
    Scope,
)
from common.models.pack import Pack
from common.models.refine import (
    ASSUMPTION,
    CLARIFICATION,
    CORRECTION,
    DECISION,
    GAP_SEED,
    GOTCHA,
    INSIGHT,
    LESSON,
    ROUNDS,
    Answer,
    IngestResult,
    Insight,
    Question,
    RefinementRun,
    RefineResult,
)

__all__ = [
    "ASSUMPTION",
    "ATTACHMENT",
    "BITBUCKET",
    "CLARIFICATION",
    "CODEGRAPH",
    "CONFLUENCE_PAGE",
    "CORRECTION",
    "DECISION",
    "EXTERNAL_WEB",
    "FIGMA",
    "GAP_SEED",
    "GOOGLE_DOC",
    "GOTCHA",
    "INSIGHT",
    "JIRA_ISSUE",
    "LESSON",
    "ROUNDS",
    "A2AResult",
    "Answer",
    "Graph",
    "IngestResult",
    "Insight",
    "LinkRecord",
    "Note",
    "Pack",
    "Question",
    "RefineResult",
    "RefinementRun",
    "RunLog",
    "Scope",
]
