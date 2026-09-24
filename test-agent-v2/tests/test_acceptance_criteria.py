"""Acceptance criteria as data — the axis the report's coverage matrix (and its GAP rows) is built on."""

from __future__ import annotations

from common.testplan.acceptance import coverage_matrix, parse_acceptance_criteria

# Shaped like a REAL distilled Jira note: one flowing blob, sub-headings glued between criteria.
_NOTE = (
    "# [eArchive] Import a conformant transfer.zip\n\nUser story As Post Health I want ...\n\n"
    "Acceptance criteria Transfer intake and structure "
    "[ ] A  transfer.zip  is accepted on the existing endpoint.  (BR-01) "
    "[ ] Every folder, including nested folders, is recreated 1:1.  (BR-02) Entry classification "
    "[ ] Metadata files are never imported as documents.  (BR-03) "
    "[ ] A metadata file larger than  100 KB  is ignored; its document still imports. Metadata interpretation "
    "[ ] Unparseable JSON → the metadata file is ignored.  (BRule-4) No regression "
    "[ ] A ZIP with no metadata files behaves as today.  (BR-12)\n"
)


def test_parses_criteria_with_stable_ids_groups_and_rules():
    acs = parse_acceptance_criteria(_NOTE, story="jira:LUZ-158390")
    assert [a.id for a in acs] == [f"jira:LUZ-158390#AC-{i}" for i in range(1, 7)]
    assert acs[0].rules == ["BR-01"] and acs[4].rules == ["BRule-4"]
    # the sub-heading is glued to the END of the preceding criterion — it must become the NEXT group,
    # not pollute that criterion's text
    assert acs[3].text.endswith("its document still imports")
    assert [a.group for a in acs] == ["Transfer intake and structure"] * 2 + \
                                     ["Entry classification"] * 2 + \
                                     ["Metadata interpretation", "No regression"]
    assert "(BR-01)" not in acs[0].text            # rule tags are refs, not prose


def test_absent_section_yields_nothing_not_a_false_pass():
    """No criteria found must read as 'coverage not assessable', never as 'all covered'."""
    assert parse_acceptance_criteria("a story with no criteria at all", story="s") == []
    assert parse_acceptance_criteria("", story="s") == []


def test_coverage_matrix_marks_uncovered_criteria_as_gaps():
    acs = parse_acceptance_criteria(_NOTE, story="jira:LUZ-158390")
    results = [
        {"title": "folders recreated", "status": "passed",
         "source_refs": ["jira:LUZ-158390#AC-2"]},
        {"title": "metadata never a document", "status": "failed",
         "source_refs": ["jira:LUZ-158390#AC-3"]},
        {"title": "story-level only", "status": "passed", "source_refs": ["jira:LUZ-158390"]},
    ]
    m = coverage_matrix(acs, results)
    assert m["total"] == 6 and m["covered"] == 2 and m["gaps"] == 4
    by_id = {r["id"]: r for r in m["rows"]}
    assert by_id["jira:LUZ-158390#AC-2"]["status"] == "passed"
    assert by_id["jira:LUZ-158390#AC-3"]["status"] == "failed"
    assert by_id["jira:LUZ-158390#AC-1"]["status"] == "gap"
    # a story-level citation covers NOTHING — that is precisely why per-AC ids exist
    assert all(r["status"] == "gap" for r in m["rows"] if r["id"] != "jira:LUZ-158390#AC-2"
               and r["id"] != "jira:LUZ-158390#AC-3")
