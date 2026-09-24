"""implement_plan emits BOUND file-upload scenarios + fixtures (executable, not NL prose)."""

from __future__ import annotations

from common.interrogate.pack import Pack
from common.models import Note
from common.testplan.models import TestPlan
from common.testplan.pack import PlanPack
from test_executor.runners import select_engine
from test_plan_definition.implement.generate.scenarios import upload_cases


def _plan(**kw) -> TestPlan:
    return TestPlan(id="plan:run-x", context_id="run-x", methodology=["api"], scope=["jira:LUZ-1"], **kw)


def _pack_with(*titles: str) -> PlanPack:
    pack = Pack(context_id="run-x", seed="LUZ-1")
    pack.notes = [Note(id=f"jira:N{i}", type="note", title=t) for i, t in enumerate(titles)]
    return PlanPack(pack=pack, understanding="")


def test_no_upload_requirement_emits_nothing():
    data, scen = upload_cases(_plan(), _pack_with("dunning status lifecycle"))
    assert data == [] and scen == []


def test_upload_note_emits_fixture_and_bound_scenario():
    data, scen = upload_cases(_plan(), _pack_with("Import a zip of documents via upload"))
    assert len(data) == 1 and len(scen) == 1
    f, s = data[0], scen[0]
    assert f.kind == "file" and f.spec.get("b64")                 # a real fixture payload
    assert s.request and s.request["method"] == "POST"
    up = s.request["upload"]
    assert up["data_ref"] == f.id and up["field"] == "file"
    # methodology=api + a bound request → routes to the ApiEngine (executable), not the LLM
    assert select_engine({"methodology": s.methodology, "request": s.request}) == "api"


def test_path_taken_from_grounding_when_present():
    _, scen = upload_cases(_plan(), _pack_with("POST /api/{tenant}/import-jobs/upload-zip accepts a zip"))
    assert scen[0].request["path"] == "/api/{tenant}/import-jobs/upload-zip"


# --- Pillar 3: spec-driven conformance scenarios --------------------------------------------------
_SPEC = {
    "openapi": "3.0.3",
    "paths": {
        "/api/version": {"get": {"responses": {"200": {}}}},
        "/api/{tenant-id}/documents": {"get": {"responses": {"200": {}, "500": {}}}},
        "/api/{tenant-id}/documents/{document-id}": {"get": {"responses": {"200": {}, "404": {}}}},
        "/api/{tenant-id}/folders/{folder-id}": {"get": {"responses": {"200": {}, "500": {}}}},
        "/api/{tenant-id}/documents/{document-id}/purge": {"delete": {"responses": {"204": {}}}},
    },
}


def test_conformance_cases_generates_from_the_spec():
    from test_plan_definition.implement.generate.scenarios import conformance_cases
    got = {s.request["path"]: s for s in conformance_cases(_SPEC, _plan())}

    # reachable happy path → spec is the oracle (expect_status 0), tenant template LEFT for the executor
    assert got["/api/version"].request["expect_status"] == 0
    assert got["/api/{tenant-id}/documents"].request["expect_status"] == 0
    assert got["/api/{tenant-id}/documents"].kind == "happy"

    # unknown id + a declared 404 → assert that 404; {tenant-id} stays templated, the doc id is filled
    doc = got["/api/{tenant-id}/documents/000000000000000000000000"]
    assert doc.request["expect_status"] == 404 and doc.kind == "negative"

    # unknown id + NO declared 404 → conformance judges (catches an undeclared status / a stale spec)
    assert got["/api/{tenant-id}/folders/000000000000000000000000"].request["expect_status"] == 0

    # WRITE verbs are never auto-generated against a live system
    assert not any("purge" in p for p in got)


def test_conformance_cases_route_to_the_api_engine():
    from test_executor.runners import select_engine
    from test_plan_definition.implement.generate.scenarios import conformance_cases
    for s in conformance_cases(_SPEC, _plan()):
        assert select_engine({"methodology": s.methodology, "request": s.request}) == "api"


def test_conformance_cases_empty_without_a_spec():
    from test_plan_definition.implement.generate.scenarios import conformance_cases
    assert conformance_cases({}, _plan()) == []
    assert conformance_cases({"paths": {}}, _plan()) == []


def test_spec_fixture_reads_the_bank_openapi_testdata():
    from common.testplan.models import TestData
    from test_plan_definition.implement.generate.pipeline import _spec_fixture
    assert _spec_fixture([]) == {}                                     # absent → {}
    assert _spec_fixture([TestData(id="x", kind="file", spec={})]) == {}  # wrong kind → {}
    td = TestData(id="s", kind="openapi", spec={"openapi_spec": _SPEC})
    assert _spec_fixture([td])["paths"] is _SPEC["paths"]
