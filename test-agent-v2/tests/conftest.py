"""Shared test fakes/fixtures — an in-memory GCS bucket (generation + CAS) and a"""

from __future__ import annotations

import os
import pathlib

import pytest
from google.adk.models.base_llm import BaseLlm
from pydantic import Field

from common.store import CASConflict

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
            raise CASConflict("generation mismatch")
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
_KGA_BANK_TARGETS = ["knowledge_gathering.agent", "knowledge_gathering.gather.agent",
                     "common.adk.interrogation", "common.adk.tools"]
_TPD_BANK_TARGETS = ["test_plan_definition.agent", "test_plan_definition.implement.agent",
                     "test_plan_definition.implement.generate.agent",
                     "test_plan_definition.implement.assured.agent",
                     "common.adk.interrogation", "common.adk.tools"]
_TEV_BANK_TARGETS = ["test_evaluation.agent"]


def patch_bank(monkeypatch, bank, targets):
    for m in targets:
        monkeypatch.setattr(f"{m}.build_bank", lambda b=bank: b)


def patch_client(monkeypatch, client):
    monkeypatch.setattr("knowledge_gathering.gather.agent.build_client", lambda c=client: c)


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


# --- Offline fake ADK model for LlmAgent(output_schema=...) planner tests (D15) ---------------
# ADK has no built-in test double, so we subclass BaseLlm to yield ONE canned reply. The LlmAgent
# turns the reply text into session.state[output_key] via ADK's own output_schema validation, so a
# valid canned JSON exercises the real save path and a malformed one exercises the ValidationError →
# degrade path. `calls` records each request so tests can assert zero-LLM (flag off) vs one call.
class FakeStructuredModel(BaseLlm):
    """A `BaseLlm` that returns `canned` as the model's only reply — no network."""

    model: str = "fake-structured"
    canned: str = "{}"
    calls: list = Field(default_factory=list)

    async def generate_content_async(self, llm_request, stream=False):
        from google.adk.models.llm_response import LlmResponse
        from google.genai import types

        self.calls.append(llm_request)
        yield LlmResponse(
            content=types.Content(role="model", parts=[types.Part(text=self.canned)]))


def fake_model(canned: str = "{}") -> FakeStructuredModel:
    """Build a `FakeStructuredModel` returning `canned` (a JSON string, or junk to force degrade)."""
    return FakeStructuredModel(canned=canned)


async def drive_gather_agent(seed, monkeypatch, *, client, hyp_model=None, leads_model=None):
    """Drive the D15 GatherAgent as root with INJECTED planner models (fakes) over a recorded client.

    Returns (reply_text, bank). The planners are opt-in now (the `explore` gate), so this helper — which
    exists to exercise the planner-on path — drives with `explore` set; inject hyp_model/leads_model
    fakes.
    """
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    import knowledge_gathering.gather.agent as ga
    from common.memory import MemoryBank
    from knowledge_gathering.gather.agent import GatherAgent
    from knowledge_gathering.gather.explore.planners.ask_llm import build_leads_agent
    from knowledge_gathering.gather.explore.planners.hypothesize import build_hypothesize_agent

    bank = MemoryBank(FakeBucket())
    monkeypatch.setattr(ga, "build_client", lambda: client)
    monkeypatch.setattr(ga, "build_bank", lambda: bank)

    hyp = build_hypothesize_agent(model=hyp_model)
    leads = build_leads_agent(model=leads_model)
    gather = GatherAgent(name="gather", hypothesize_agent=hyp, leads_agent=leads,
                         sub_agents=[hyp, leads])
    ctx_id = f"t-{seed}"
    svc = InMemorySessionService()
    await svc.create_session(app_name="kga", user_id="u", session_id=ctx_id)
    runner = Runner(app_name="kga", agent=gather, session_service=svc)
    out: list[str] = []
    async for ev in runner.run_async(
        user_id="u", session_id=ctx_id,
        new_message=types.Content(role="user", parts=[types.Part(text=f"gather {seed} explore")])):
        c = getattr(ev, "content", None)
        for p in getattr(c, "parts", None) or []:
            if getattr(p, "text", None) and getattr(c, "role", None) != "user":
                out.append(p.text)
    return " ".join(out), bank


async def run_planner_agent(agent, plan_input: dict, *, output_key: str):
    """Run a planner LlmAgent once via a Runner with `plan_input` seeded into state; return the state
    value at `output_key` (ADK applies the validated output_schema dict to the session)."""
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    from knowledge_gathering.gather.explore.planners.schemas import PLAN_INPUT_KEY

    svc = InMemorySessionService()
    await svc.create_session(app_name="t", user_id="u", session_id="s",
                             state={PLAN_INPUT_KEY: plan_input})
    runner = Runner(app_name="t", agent=agent, session_service=svc)
    async for _ in runner.run_async(
        user_id="u", session_id="s",
        new_message=types.Content(role="user", parts=[types.Part(text="go")])):
        pass
    sess = await svc.get_session(app_name="t", user_id="u", session_id="s")
    return sess.state.get(output_key)


# --- Offline fake CloudProvider (X-tiers 5/6/7) — the port makes the fakes clean (no google client) --
class FakeCloudProvider:
    """A `CloudProvider` double: canned discovery + logs, no cloud SDK. Inject via the module-level
    `_providers` seam (cloud_discover / cloud_service). `discover_fn`/`read_logs_fn` may raise to
    exercise per-provider/env isolation and the unconfigured-degrade paths."""

    def __init__(self, name="fake", *, envs=("dev",), discover_fn=None, read_logs_fn=None, configured=True):
        self.name = name
        self._envs = list(envs)
        self._discover_fn = discover_fn or (lambda env_key: [])
        self._read_logs_fn = read_logs_fn or (lambda ref, days, cap, min_severity: [])
        self._configured = configured

    def is_configured(self):
        return self._configured

    def env_keys(self):
        return list(self._envs)

    def discover(self, env_key):
        return self._discover_fn(env_key)

    def read_logs(self, ref, days, *, cap, min_severity="WARNING"):
        return self._read_logs_fn(ref, days, cap, min_severity)
