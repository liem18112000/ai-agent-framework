"""The `transfer.zip` fixture set for a ZIP-import story (LUZ-158390's Test notes).

Each case is a real, valid ZIP built in memory and shipped as a bank `TestData(kind="file")` fixture, so
the executor can upload it without touching the filesystem.

HONEST SCOPE — read before citing acceptance criteria on these:
a single upload request proves only that the transfer was ACCEPTED (a job came back). It does NOT prove
what the story actually promises — that a metadata file was paired, that `Thumbs.db` was skipped, that an
unparseable JSON still produced a document. Proving those needs the async chain the executor cannot yet
run: upload -> poll the job to DONE -> read the resulting eArchive content back and compare. So the
generated scenarios cite only the INTAKE criteria they genuinely verify, and each case records the
criterion it is *built to exercise* in `spec["exercises"]` for whoever writes the verification step. A
scenario that claimed AC-16 because an upload returned 200 would be a false pass, which is worse than the
gap it hides.
"""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass, field

from common.memory.bank import _slug
from common.testplan.models import HAPPY, NEGATIVE, TestData, TestPlan, TestScenario

#: The seven top-level fields the story allow-lists.
_META = {"senderTenantId": "t-sender", "senderCompanyId": "c-sender", "senderName": "Post Health",
         "documentTitle": "Lab report", "documentTypes": ["HEALTH"],
         "documentReferenceDate": "2026-09-01", "healthData": {"code": "LAB"}}
_PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
        b"trailer<</Size 4/Root 1 0 R>>\n%%EOF\n")


@dataclass
class ZipCase:
    """One fixture: the entries to write, and the criterion it is built to exercise."""

    key: str
    title: str
    entries: list                      # [(path, bytes)] — written in order
    exercises: str = ""                # the AC this data is FOR (not what an upload alone proves)
    kind: str = HAPPY
    note: str = field(default="")


def _meta(**over) -> bytes:
    return json.dumps({**_META, **over}, ensure_ascii=False).encode("utf-8")


def cases() -> list[ZipCase]:
    """The nine fixtures named in the story's Test notes, each shaped to one classification rule."""
    doc = "Medical documents/an image.pdf"
    return [
        ZipCase("valid-metadata", "a document paired with its metadata file",
                [(doc, _PDF), (doc + ".metadata.json", _meta())], exercises="metadata pairing"),
        ZipCase("no-metadata", "a document with no metadata file",
                [(doc, _PDF)], exercises="document without metadata imports, titled from its filename"),
        ZipCase("unparseable-metadata", "a metadata file that is not valid JSON",
                [(doc, _PDF), (doc + ".metadata.json", b"{not json at all")],
                exercises="unparseable JSON ignored, document still imported", kind=NEGATIVE),
        ZipCase("orphaned-metadata", "a metadata file with no matching document",
                [("Medical documents/ghost.pdf.metadata.json", _meta())],
                exercises="orphaned metadata rejected per-entry, transfer continues", kind=NEGATIVE),
        ZipCase("disallowed-element", "metadata carrying a non-allow-listed top-level element",
                [(doc, _PDF), (doc + ".metadata.json", _meta(_internalFlag="x", sneaky="y"))],
                exercises="unknown top-level elements silently dropped", kind=NEGATIVE),
        ZipCase("oversized-metadata", "a metadata file larger than 100 KB",
                [(doc, _PDF), (doc + ".metadata.json",
                               json.dumps({**_META, "pad": "x" * 110_000}).encode())],
                exercises="metadata >100 KB ignored, document still imports", kind=NEGATIVE),
        ZipCase("os-artefacts", "OS artefacts alongside a real document",
                [("__MACOSX/._an image.pdf", b"junk"), (".DS_Store", b"junk"),
                 ("Medical documents/Thumbs.db", b"junk"), (doc, _PDF)],
                exercises="__MACOSX/.DS_Store/Thumbs.db/dot-prefixed ignored, not reported as failures"),
        ZipCase("nested-folders", "a nested folder tree",
                [("Medical documents/2026/Q3/report.pdf", _PDF),
                 ("Medical documents/2026/Q3/report.pdf.metadata.json", _meta()),
                 ("Vaccination/PONTI-A-17.7.2026.pdf", _PDF)],
                exercises="folder tree recreated 1:1 including nesting"),
        ZipCase("utf8-names", "UTF-8 filenames and titles",
                [("Medizinische Dokumente/Patientenverfügung.pdf", _PDF),
                 ("Medizinische Dokumente/Patientenverfügung.pdf.metadata.json",
                  _meta(documentTitle="Meine Patientenverfügung"))],
                exercises="metadata read as UTF-8; umlaut titles round-trip intact"),
    ]


def build_transfer_zip(case: ZipCase) -> bytes:
    """Build the case's ZIP in memory. Entry names are written UTF-8 so the umlaut case is real."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path, data in case.entries:
            info = zipfile.ZipInfo(path)
            info.flag_bits |= 0x800                  # EFS: entry name is UTF-8 (the Gap-3 legacy/NFC case)
            z.writestr(info, data)
    return buf.getvalue()


def transfer_zip_cases(plan: TestPlan, upload_path: str, *, now: str = "",
                       intake_refs: list | None = None) -> tuple[list[TestData], list[TestScenario]]:
    """The fixture set + one upload scenario per case.

    `intake_refs` are the acceptance-criterion ids an upload REQUEST genuinely proves (intake/job
    creation). They are the only ids cited: what each fixture is *built* to exercise lives in the
    fixture's `spec["exercises"]`, because verifying it needs the upload -> poll -> read-back chain."""
    import base64

    data: list[TestData] = []
    scenarios: list[TestScenario] = []
    for c in cases():
        fid = f"test-data:{plan.context_id}:zip:{c.key}"
        blob = build_transfer_zip(c)
        data.append(TestData(
            id=fid, kind="file", plan_id=plan.id,
            spec={"filename": f"transfer-{c.key}.zip", "content_type": "application/zip",
                  "b64": base64.b64encode(blob).decode(), "exercises": c.exercises,
                  "purpose": f"transfer.zip fixture — {c.title}"},
            source_refs=plan.source_refs[:1], created_at=now))
        scenarios.append(TestScenario(
            id=f"scenario:{plan.context_id}:zip:{_slug(c.key)}", plan_id=plan.id,
            title=f"Upload a transfer.zip — {c.title}", kind=c.kind, methodology="api",
            description=("The transfer is accepted and an import job is returned. NOTE: this asserts "
                         f"INTAKE only; '{c.exercises}' needs the job polled to DONE and the resulting "
                         "eArchive content compared against the ZIP."),
            rationale="confirms the transfer is accepted for import",
            data_refs=[fid], source_refs=list(intake_refs or []), created_at=now,
            request={"method": "POST", "path": upload_path, "expect_status": 200,
                     "upload": {"field": "file", "data_ref": fid}}))
    return data, scenarios
