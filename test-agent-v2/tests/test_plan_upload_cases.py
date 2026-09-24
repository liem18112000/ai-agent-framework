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
