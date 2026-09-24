"""The transfer.zip fixture set — real ZIPs, one per classification rule in the story's Test notes."""

from __future__ import annotations

import base64
import io
import json
import zipfile

from common.testplan.models import TestPlan
from test_plan_definition.implement.generate.transfer_zip import (
    build_transfer_zip,
    cases,
    transfer_zip_cases,
)


def _plan() -> TestPlan:
    return TestPlan(id="p", context_id="ctx", methodology=["api"], scope=["jira:LUZ-158390"],
                    source_refs=["jira:LUZ-158390"])


def test_every_named_case_builds_a_valid_zip():
    keys = {c.key for c in cases()}
    assert keys == {"valid-metadata", "no-metadata", "unparseable-metadata", "orphaned-metadata",
                    "disallowed-element", "oversized-metadata", "os-artefacts", "nested-folders",
                    "utf8-names"}
    for c in cases():
        with zipfile.ZipFile(io.BytesIO(build_transfer_zip(c))) as z:
            assert z.testzip() is None                       # a real, readable ZIP
            assert z.namelist() == [p for p, _ in c.entries]


def test_fixtures_encode_the_rule_each_one_targets():
    by_key = {c.key: c for c in cases()}

    def entries(key):
        with zipfile.ZipFile(io.BytesIO(build_transfer_zip(by_key[key]))) as z:
            return {n: z.read(n) for n in z.namelist()}

    # pairing: metadata sits beside its document, named <document>.metadata.json
    e = entries("valid-metadata")
    assert "Medical documents/an image.pdf.metadata.json" in e
    assert set(json.loads(e["Medical documents/an image.pdf.metadata.json"])) == {
        "senderTenantId", "senderCompanyId", "senderName", "documentTitle", "documentTypes",
        "documentReferenceDate", "healthData"}
    # unparseable really is unparseable
    bad = entries("unparseable-metadata")["Medical documents/an image.pdf.metadata.json"]
    try:
        json.loads(bad); raise AssertionError("fixture should not be valid JSON")
    except ValueError:
        pass
    # orphan has metadata but NO document
    assert all(n.endswith(".metadata.json") for n in entries("orphaned-metadata"))
    # oversized is genuinely over the 100 KB rule
    assert len(entries("oversized-metadata")["Medical documents/an image.pdf.metadata.json"]) > 100 * 1024
    # OS artefacts present alongside a real document
    names = entries("os-artefacts")
    assert "__MACOSX/._an image.pdf" in names and ".DS_Store" in names
    assert any(n.endswith("Thumbs.db") for n in names) and "Medical documents/an image.pdf" in names
    # nesting is deeper than one level
    assert any(n.count("/") >= 3 for n in entries("nested-folders"))
    # UTF-8 name AND title survive the round-trip
    u = entries("utf8-names")
    assert any("Patientenverfügung" in n for n in u)
    meta = json.loads(next(v for k, v in u.items() if k.endswith(".metadata.json")).decode("utf-8"))
    assert meta["documentTitle"] == "Meine Patientenverfügung"


def test_scenarios_cite_only_what_an_upload_actually_proves():
    """A single upload proves INTAKE. Citing 'unparseable JSON still imports' on it would be a false
    pass — that needs upload -> poll -> read-back. The target rule stays on the fixture instead."""
    data, scen = transfer_zip_cases(_plan(), "/api/{tenant-id}/import-jobs/upload-zip",
                                    intake_refs=["jira:LUZ-158390#AC-1"])
    assert len(data) == len(scen) == 9
    for s in scen:
        assert s.source_refs == ["jira:LUZ-158390#AC-1"]      # intake only — never the deep criterion
        assert s.request["upload"]["data_ref"] in {d.id for d in data}
        assert "INTAKE only" in s.description
    assert all(d.spec["exercises"] for d in data)             # the real target is recorded on the fixture
    # the fixture bytes round-trip through the bank's base64 transport
    blob = base64.b64decode(data[0].spec["b64"])
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        assert z.testzip() is None
