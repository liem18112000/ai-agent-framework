"""Test Executor — run ledger + failure-triage classifier (offline, in-memory)."""

from __future__ import annotations

from test_executor.runner import classify_failure, triage
from test_executor.store import InMemoryExecStore, env_id


def test_classify_failure_buckets():
    assert classify_failure({"flaky": True}) == "Flaky"
    assert classify_failure({"message": "Connection refused"}) == "Environment"
    assert classify_failure({"message": "selector not found: #btn"}) == "Heal"
    assert classify_failure({"message": "AssertionError: expected 3"}) == "Bug"
    # unknown text defaults to Bug — a real regression must fail loud, never silently heal/quarantine
    assert classify_failure({"message": "totally unrecognised"}) == "Bug"


def test_triage_maps_all():
    out = triage([{"message": "timeout waiting for element"}, {"message": "expected 200"}])
    assert [v["verdict"] for v in out] == ["Heal", "Bug"]


class _FakeDecision:
    """A DecisionProvider double — returns a fixed Choice verdict at a fixed confidence."""

    name = "fake"

    def __init__(self, value, confidence):
        self._value, self._confidence = value, confidence

    def is_configured(self):
        return True

    def choice(self, state, options, instructions):
        from common.adk.providers import Verdict
        return Verdict(value=self._value, probs=None, confidence=self._confidence)

    def score(self, *a, **k):
        raise NotImplementedError

    def noul(self, *a, **k):
        raise NotImplementedError


def test_triage_jev_confident_overrides_heuristic(monkeypatch):
    # message reads Bug by heuristic; a confident JEV Choice wins
    monkeypatch.setattr("common.adk.providers.get_decision_provider", lambda: _FakeDecision("Environment", 0.9))
    assert triage([{"message": "AssertionError: expected 3"}])[0]["verdict"] == "Environment"


def test_triage_jev_low_confidence_falls_back(monkeypatch):
    monkeypatch.setattr("common.adk.providers.get_decision_provider", lambda: _FakeDecision("Environment", 0.2))
    assert triage([{"message": "AssertionError: expected 3"}])[0]["verdict"] == "Bug"  # heuristic tail


def test_triage_flaky_not_rejudged_by_jev(monkeypatch):
    monkeypatch.setattr("common.adk.providers.get_decision_provider", lambda: _FakeDecision("Bug", 0.99))
    assert triage([{"message": "x", "flaky": True}])[0]["verdict"] == "Flaky"  # proven-flaky short-circuits


def test_triage_default_off_is_heuristic(monkeypatch):
    monkeypatch.setattr("common.adk.providers.get_decision_provider", lambda: None)
    assert triage([{"message": "selector not found"}])[0]["verdict"] == "Heal"


async def test_ledger_roundtrip():
    s = InMemoryExecStore()
    eid = await s.upsert_env("CTX", "dev", base_url="http://dev")
    assert eid == env_id("CTX", "dev") == "CTX:dev"
    rid = await s.start_run("CTX", eid)
    await s.finish_run(rid, status="done", summary={"passed": 1}, signals={"stub": True})
    run = await s.get_run(context_id="CTX")
    assert run["id"] == rid and run["status"] == "done" and run["summary"]["passed"] == 1
    assert (await s.get_run(run_id=rid))["environment_id"] == "CTX:dev"


async def test_upsert_env_idempotent():
    s = InMemoryExecStore()
    await s.upsert_env("CTX", "dev")
    await s.upsert_env("CTX", "dev", base_url="http://x")
    envs = await s.list_environments("CTX")
    assert len(envs) == 1 and envs[0]["base_url"] == "http://x"
