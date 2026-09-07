"""E6 — the Agent-Engine deploy script parses + resolves agents offline (vertexai is lazy)."""

from __future__ import annotations

import importlib.util
import pathlib

_DEPLOY = pathlib.Path(__file__).resolve().parents[1] / "deployment" / "deploy.py"


def _load():
    spec = importlib.util.spec_from_file_location("deploy_mod", _DEPLOY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # module-level imports are stdlib only (vertexai imported lazily)
    return mod


def test_cli_parses_and_resolves_agent():
    deploy = _load()
    args = deploy.build_parser().parse_args(["--create", "--agent", "testing_agent"])
    assert args.create and args.agent == "testing_agent"

    root = deploy.resolve_agent("testing_agent")
    assert root.name == "testing_agent"
    # every canonical agent is a valid deploy target
    assert set(deploy._AGENTS) == {"testing_agent", "knowledge_gathering", "test_plan_definition", "test_evaluation"}
    assert deploy.REQUIREMENTS and deploy.EXTRA_PACKAGES == ["./src"]


def test_delete_requires_resource_id():
    deploy = _load()
    import pytest

    with pytest.raises(SystemExit):
        deploy.main(["--delete"])  # no --resource-id → SystemExit before touching vertexai
