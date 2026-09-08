"""Shared test fakes/fixtures — an in-memory GCS bucket (generation + CAS) and a"""

from __future__ import annotations

import os
import pathlib

import pytest
from google.api_core.exceptions import PreconditionFailed

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session", autouse=True)
def _offline_default_no_vertex():
    """Offline hygiene (session-wide). Each agent package's `__init__` runs `load_dotenv()`, so a local
    `.env` carrying VERTEX_PROJECT/LOCATION/MODEL leaks into `os.environ` and flips `vertex_config()`
    truthy — pushing the "no-LLM" interrogation (refine/define/implement) onto the real Vertex network,
    which hangs the suite.

    We set them to "" (not pop): `vertex_config()` treats "" as falsy → None → heuristic path, AND
    `load_dotenv(override=False)` (the default) will not overwrite an already-present key — so a *lazy*
    package import mid-test (e.g. `testing_agent` inside `test_adk_autonomous`) can't refill them.
    Session scope is required (the eval pipeline fixtures are module-scoped and run before any
    function-scoped clear). Tests that exercise the LLM path set real values via their own
    function-scoped monkeypatch, which applies within — and reverts after — their test."""
    saved = {k: os.environ.get(k) for k in ("VERTEX_PROJECT", "VERTEX_LOCATION", "VERTEX_MODEL")}
    for k in saved:
        os.environ[k] = ""
    yield
    for k, v in saved.items():
        os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


class FakeBlob:
    def __init__(self, bucket, name):
        self._b, self.name = bucket, name

    @property
    def generation(self):
        return self._b.gens.get(self.name, 0)

    def download_as_text(self):
        return self._b.store[self.name]

    def upload_from_string(self, data, content_type=None, if_generation_match=None):
        cur = self._b.gens.get(self.name, 0)
        if if_generation_match is not None and if_generation_match != cur:
            raise PreconditionFailed("generation mismatch")
        self._b.store[self.name] = data
        self._b.gens[self.name] = cur + 1


class FakeBucket:
    def __init__(self):
        self.store: dict[str, str] = {}
        self.gens: dict[str, int] = {}

    def blob(self, name):
        return FakeBlob(self, name)

    def get_blob(self, name):
        return FakeBlob(self, name) if name in self.store else None


def load_fixture_bucket(pack_name: str) -> FakeBucket:
    """Hydrate a FakeBucket from tests/fixtures/<pack_name>/ (keys = paths under it)."""
    bucket = FakeBucket()
    root = FIXTURES / pack_name
    for path in root.rglob("*.json"):
        key = path.relative_to(root).as_posix()
        bucket.store[key] = path.read_text(encoding="utf-8")
        bucket.gens[key] = 1
    return bucket


@pytest.fixture
def fake_bucket() -> FakeBucket:
    return FakeBucket()


@pytest.fixture
def pack_bucket() -> FakeBucket:
    return load_fixture_bucket("pack_run-6f2a")


# --- ADK-native in-process A2A backend + agent-module patch helpers (C5) ---
_KGA_BANK_TARGETS = ["knowledge_gathering.agent", "knowledge_gathering.agents.gather_agent",
                     "common.adk.interrogation", "common.adk.tools"]
_TPD_BANK_TARGETS = ["test_plan_definition.agent", "test_plan_definition.agents.implement_agent",
                     "common.adk.interrogation", "common.adk.tools"]
_TEV_BANK_TARGETS = ["test_evaluation.agent"]


def patch_bank(monkeypatch, bank, targets):
    for m in targets:
        monkeypatch.setattr(f"{m}.build_bank", lambda b=bank: b)


def patch_client(monkeypatch, client):
    monkeypatch.setattr("knowledge_gathering.agents.gather_agent.build_client", lambda c=client: c)


def adk_a2a_app(build_root_agent):
    """An in-process ADK-native A2A ASGI app (to_a2a) — the drop-in for the deleted a2a test _app()."""
    from google.adk.a2a.utils.agent_to_a2a import to_a2a
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService

    root = build_root_agent()
    runner = Runner(app_name=root.name, agent=root, session_service=InMemorySessionService())
    return to_a2a(root, runner=runner)


async def drive_adk(build_root_agent, text, *, session_id="s"):
    """Drive a custom ADK agent once through a Runner; return the joined non-user event text."""
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    svc = InMemorySessionService()
    await svc.create_session(app_name="t", user_id="u", session_id=session_id)
    runner = Runner(app_name="t", agent=build_root_agent(), session_service=svc)
    out: list[str] = []
    async for ev in runner.run_async(
        user_id="u", session_id=session_id,
        new_message=types.Content(role="user", parts=[types.Part(text=text)]),
    ):
        c = getattr(ev, "content", None)
        for p in getattr(c, "parts", None) or []:
            if getattr(p, "text", None) and getattr(c, "role", None) != "user":
                out.append(p.text)
    return " ".join(out)
