"""Acceptance criteria as DATA — the axis a test-completion report's coverage matrix is built on.

Why this exists: a report's central table is `AC -> covering scenario(s) -> result -> evidence`, and its
whole value is the GAP row — an AC with no covering scenario. Story-level traceability (a scenario citing
`jira:LUZ-158390`) cannot produce that table: every scenario cites the same id, so nothing is ever
uncovered and the matrix silently reads as complete. Each criterion therefore needs its OWN stable id.

Parsing is deliberately dumb and deterministic (checkbox lines under an "Acceptance criteria" heading),
because a mis-parsed AC set is worse than none: it would invent coverage rows for things nobody promised.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

#: A criterion line in a distilled Jira note: "[ ] The transfer is imported ... (BR-01)".
_BOX = re.compile(r"\[[ xX]?\]\s*(?P<text>.+?)\s*$")
#: The rule tags teams attach to a criterion — kept as extra refs, never as the identity (they repeat).
_RULE = re.compile(r"\((?P<tag>(?:BR|BRule|AC)[- ]?[0-9]+(?:\s*,\s*(?:BR|BRule|AC)[- ]?[0-9]+)*)\)")
_HEADING = re.compile(r"acceptance criteria", re.IGNORECASE)
#: Headings that END the criteria block — anything after these is not a criterion.
_STOP = re.compile(r"^(definition of done|technical notes|test notes|out of scope|links|full content)\b", re.IGNORECASE)


@dataclass
class AcceptanceCriterion:
    """ONE acceptance criterion, with an id stable enough to hang a coverage row on.

    `id` is positional (`<story>#AC-3`) because the rule tags repeat — BR-01 covers three separate
    criteria in LUZ-158390, so a tag cannot identify a row. `rules` keeps those tags for reference."""

    id: str
    text: str
    group: str = ""                                  # the sub-heading it sat under, e.g. "Entry classification"
    rules: list = field(default_factory=list)        # ["BR-01", "BRule-5"] — reference only, not identity

    def as_dict(self) -> dict:
        return asdict(self)


#: A distilled note is one flowing blob, so a sub-heading ends up glued between the previous criterion
#: and the next checkbox: "...position in the ZIP.  (BR-01, BR-02) Entry classification [ ] An entry...".
#: Match that trailing Title-case phrase (1–4 words) so it becomes the NEXT group instead of polluting
#: the criterion's text — anchored to a preceding '.' or ')' so ordinary sentence tails are left alone.
_TRAIL_HEADING = re.compile(r"(?:(?<=\.)|(?<=\)))\s+(?P<head>[A-Z][A-Za-z-]*(?:\s+[a-z][A-Za-z-]*){0,3})\s*$")


def parse_acceptance_criteria(text: str, *, story: str) -> list[AcceptanceCriterion]:
    """Extract the checkbox criteria that follow an "Acceptance criteria" heading in a distilled note.

    Returns [] when the section is absent — an empty list means "no criteria found", which a report must
    surface as "coverage not assessable", NOT as "everything covered"."""
    if not text or not _HEADING.search(text):
        return []
    tail = text[_HEADING.search(text).end():]
    out: list[AcceptanceCriterion] = []
    group = ""
    for raw in re.split(r"(?=\[[ xX]?\])", tail):
        chunk = raw.strip()
        if not chunk:
            continue
        m = _BOX.match(chunk.split("\n")[0]) or _BOX.match(chunk)
        if not m:                                     # prose before the first checkbox = the first heading
            head = chunk.split("[")[0].strip()
            if head:
                if _STOP.match(head):
                    break
                group = head.splitlines()[-1].strip()[:60]
            continue
        body = m.group("text")
        next_group = ""
        if (h := _TRAIL_HEADING.search(body)):        # peel the next sub-heading off this criterion's tail
            next_group = h.group("head").strip()
            body = body[:h.start()].strip()
        if _STOP.match(body):
            break
        rules = [r.strip().replace(" ", "-") for m2 in _RULE.finditer(body)
                 for r in m2.group("tag").split(",")]
        out.append(AcceptanceCriterion(id=f"{story}#AC-{len(out) + 1}",
                                       text=_RULE.sub("", body).strip(" .;"), group=group, rules=rules))
        if next_group:
            group = next_group
    return out


def coverage_matrix(criteria: list, results: list) -> dict:
    """Build the report's coverage matrix: one row per criterion, with the scenarios that CITE it.

    A scenario covers a criterion when the criterion's id appears in the scenario's `source_refs` — which
    is why per-AC ids matter. `status` is the worst outcome of its covering scenarios: no scenario at all
    is a **gap** (the row that makes the report worth writing), any failure is `failed`, otherwise
    `passed`. Returns {rows, covered, total, gaps} so a caller can state coverage without recomputing."""
    rows, gaps = [], 0
    for c in criteria:
        cid = c.id if isinstance(c, AcceptanceCriterion) else c.get("id")
        ctext = c.text if isinstance(c, AcceptanceCriterion) else c.get("text", "")
        covering = [r for r in results if cid in (r.get("source_refs") or [])]
        if not covering:
            status, gaps = "gap", gaps + 1
        elif any(r.get("status") == "failed" for r in covering):
            status = "failed"
        elif all(r.get("status") == "passed" for r in covering):
            status = "passed"
        else:
            status = "unproven"                       # ran but unbound → a result without evidence
        rows.append({"id": cid, "text": ctext, "status": status,
                     "scenarios": [r.get("title") or r.get("id") for r in covering]})
    return {"rows": rows, "total": len(rows), "covered": len(rows) - gaps, "gaps": gaps}
