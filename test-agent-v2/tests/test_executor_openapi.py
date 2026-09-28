"""Test Executor Pillar 3 — OpenAPI-grounded API execution + conformance oracle (offline)."""

from __future__ import annotations

import httpx

from test_executor import runners
from test_executor.oracle import (
    conformance_failures,
    match_operation,
    operation_catalog,
    parse_operations,
)
from test_executor.runners import ApiEngine

_SPEC = {
    "openapi": "3.0.0",
    "components": {"schemas": {"Doc": {"type": "object", "required": ["id"],
                                       "properties": {"id": {"type": "string"}}}}},
    "paths": {
        "/documents": {"post": {"summary": "create a document",
                                "responses": {"201": {"content": {"application/json": {
                                    "schema": {"$ref": "#/components/schemas/Doc"}}}}}}},
        "/documents/{id}": {"get": {"summary": "get a document",
                                    "responses": {"200": {"content": {"application/json": {
                                        "schema": {"$ref": "#/components/schemas/Doc"}}}}}}},
    },
}


def test_parse_and_catalog():
    ops = parse_operations(_SPEC)
    assert {(o.method, o.path) for o in ops} == {("POST", "/documents"), ("GET", "/documents/{id}")}
    cat = operation_catalog(ops)
    assert "POST /documents — create a document" in cat


def test_match_operation_exact_and_templated():
    ops = parse_operations(_SPEC)
    assert match_operation(ops, "POST", "/documents").path == "/documents"
    assert match_operation(ops, "GET", "/documents/abc123").path == "/documents/{id}"   # templated
    assert match_operation(ops, "DELETE", "/documents") is None                            # method not in spec


def test_conformance_status_and_schema():
    ops = parse_operations(_SPEC)
    op = match_operation(ops, "POST", "/documents")
    # conforming: declared 201 + a valid Doc body
    assert conformance_failures(_SPEC, op, status=201, body_text='{"id":"x"}',
                                content_type="application/json") == []
    # undeclared status
    assert any("not declared" in m for m in
               conformance_failures(_SPEC, op, status=418, body_text="{}", content_type="application/json"))
    # schema violation (missing required 'id')
    assert any("does not conform" in m for m in
               conformance_failures(_SPEC, op, status=201, body_text='{"nope":1}',
                                    content_type="application/json"))


async def test_api_engine_applies_spec_conformance(monkeypatch):
    # a real-endpoint call whose body violates the declared schema → conformance failure surfaces
    monkeypatch.setattr(runners, "_transport",
                        httpx.MockTransport(lambda r: httpx.Response(201, json={"nope": 1})))
    spec_ctx = {"spec": _SPEC, "ops": parse_operations(_SPEC)}
    res = await ApiEngine().run({"request": {"method": "POST", "path": "/documents", "expect_status": 201}},
                                base_url="https://svc", spec=spec_ctx)
    assert res.ran and not res.passed
    assert any("does not conform" in o.message for o in res.outcomes if not o.ok)


async def test_api_engine_spec_conformance_pass(monkeypatch):
    monkeypatch.setattr(runners, "_transport",
                        httpx.MockTransport(lambda r: httpx.Response(201, json={"id": "d1"})))
    spec_ctx = {"spec": _SPEC, "ops": parse_operations(_SPEC)}
    res = await ApiEngine().run({"request": {"method": "POST", "path": "/documents", "expect_status": 201}},
                                base_url="https://svc", spec=spec_ctx)
    assert res.ran and res.passed        # declared status + conforming body → all green


async def test_api_engine_multipart_upload(monkeypatch, tmp_path):
    # a scenario with an `upload` → ApiEngine sends multipart/form-data carrying the file bytes
    seen = {}

    def handler(r: httpx.Request) -> httpx.Response:
        seen["ctype"] = r.headers.get("content-type", "")
        seen["body"] = r.content
        return httpx.Response(200, json={"_id": "job-1"})

    monkeypatch.setattr(runners, "_transport", httpx.MockTransport(handler))
    # bytes are supplied INLINE (resolved from a bank fixture by run_suite) — never a local path (exfil guard)
    res = await ApiEngine().run(
        {"request": {"method": "POST", "path": "/api/t/import-jobs/upload-zip", "expect_status": 200,
                     "upload": {"field": "file", "filename": "t.zip", "content": b"PK\x03\x04zipbytes",
                                "content_type": "application/zip"}}},
        base_url="https://svc")
    assert res.ran and res.passed
    assert seen["ctype"].startswith("multipart/form-data")
    assert b"zipbytes" in seen["body"] and b"t.zip" in seen["body"]


async def test_resolve_upload_refs_injects_bank_bytes(monkeypatch):
    # a bound upload scenario referencing a bank TestData → run_suite injects the fixture bytes
    import base64

    from common.testplan.models.scenario import TestData
    from test_executor.runners import suite as R
    td = TestData(id="zip1", kind="file",
                  spec={"filename": "a.zip", "content_type": "application/zip",
                        "b64": base64.b64encode(b"PKzipbytes").decode()})
    monkeypatch.setattr("common.memory.factory.build_bank", lambda: object())
    monkeypatch.setattr("common.testplan.memory.writers.read_test_data", lambda bank, ctx: [td])
    scen = [{"request": {"method": "POST", "path": "/upload",
                         "upload": {"field": "file", "data_ref": "zip1"}}}]
    await R._resolve_upload_refs(scen, "ctx")
    up = scen[0]["request"]["upload"]
    assert up["content"] == b"PKzipbytes"
    assert up["filename"] == "a.zip" and up["content_type"] == "application/zip"


def test_subst_path_substitutes_and_leaves_unknown_literal():
    from test_executor.runners import _subst_path
    pv = {"tenant-id": "T1", "id": "9"}
    assert _subst_path("/api/{tenant-id}/import-jobs/{id}", pv) == "/api/T1/import-jobs/9"
    assert _subst_path("/api/{unknown}/x", pv) == "/api/{unknown}/x"   # unknown → left literal (honest 404)
    assert _subst_path("/api/version", pv) == "/api/version"            # no template
    assert _subst_path("/api/{tenant-id}", None) == "/api/{tenant-id}"  # no path_vars


async def test_api_engine_substitutes_path_vars(monkeypatch):
    seen = {}

    def h(r: httpx.Request) -> httpx.Response:
        seen["url"] = str(r.url)
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(runners, "_transport", httpx.MockTransport(h))
    res = await ApiEngine().run(
        {"request": {"method": "GET", "path": "/api/{tenant-id}/documents", "expect_status": 200}},
        base_url="https://svc", path_vars={"tenant-id": "T7"})
    assert res.ran and res.passed
    assert seen["url"] == "https://svc/api/T7/documents"    # {tenant-id} resolved from the env's path_vars


# --- the executor -> TPD spec handoff -------------------------------------------------------------
async def test_persist_spec_caches_the_fixture_for_implement(monkeypatch):
    """The executor is the only side that can reach an internal spec; TPD needs it at planning time."""
    from common.memory import MemoryBank
    from common.store.memory import InMemoryObjectStore
    from common.testplan.memory.writers import read_test_data
    from test_executor.runners import suite as R

    bank = MemoryBank(InMemoryObjectStore())
    monkeypatch.setattr("common.memory.factory.build_bank", lambda: bank)
    await R._persist_spec("CTX", _SPEC, "/api/openapi")

    td = read_test_data(bank, "CTX")
    fx = next(d for d in td if d.kind == "openapi")
    assert fx.spec["openapi_spec"] == _SPEC and fx.spec["spec_url"] == "/api/openapi"
    # and TPD's pipeline reads exactly this shape back
    from test_plan_definition.implement.generate.pipeline import _spec_fixture
    assert _spec_fixture(td) == _SPEC


async def test_persist_spec_preserves_other_fixtures_and_is_idempotent(monkeypatch):
    from common.memory import MemoryBank
    from common.store.memory import InMemoryObjectStore
    from common.testplan.memory.writers import read_test_data, write_test_data
    from common.testplan.models import TestData
    from test_executor.runners import suite as R

    bank = MemoryBank(InMemoryObjectStore())
    monkeypatch.setattr("common.memory.factory.build_bank", lambda: bank)
    write_test_data(bank, "CTX", [TestData(id="keep", kind="file", spec={"b64": "x"})])

    writes = []
    real = write_test_data
    monkeypatch.setattr("common.testplan.memory.writers.write_test_data",
                        lambda b, c, d: (writes.append(len(d)), real(b, c, d))[1])
    await R._persist_spec("CTX", _SPEC, "/api/openapi")
    await R._persist_spec("CTX", _SPEC, "/api/openapi")     # unchanged → must NOT rewrite

    assert writes == [2]                                     # one write, carrying BOTH fixtures
    assert {d.id for d in read_test_data(bank, "CTX")} == {"keep", "test-data:CTX:openapi"}


async def test_persist_spec_never_fails_the_run(monkeypatch):
    from test_executor.runners import suite as R

    def boom():
        raise RuntimeError("bank down")
    monkeypatch.setattr("common.memory.factory.build_bank", boom)
    await R._persist_spec("CTX", _SPEC, "/api/openapi")      # logs + returns; no raise
