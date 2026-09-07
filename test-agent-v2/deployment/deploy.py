"""Deploy a v2 ADK agent to Vertex **Agent Engine** (E6) — an option alongside Cloud Run.

Canonical adk-samples deploy shape: wrap `root_agent` in `AdkApp(enable_tracing=True)` and
`agent_engines.create(...)` with pinned `requirements` + `extra_packages`. This is an ADDITIONAL
target — the Cloud Run `to_a2a` path (and the MCP bridge) stays the primary contract; Agent Engine
suits the autonomous consumer (`testing_agent`), which needs no bridge.

    python -m deployment.deploy --create --agent testing_agent
    python -m deployment.deploy --list
    python -m deployment.deploy --delete --resource-id <id>

Project / location / bucket resolve from flags, else env (GOOGLE_CLOUD_PROJECT / VERTEX_PROJECT, …).
`vertexai` is imported lazily so this module + its CLI parse offline (no google-cloud-aiplatform[adk]).
"""

from __future__ import annotations

import argparse
import importlib
import os

# name → the module exposing `root_agent` (the canonical agent.py, E1). Agent Engine changes the
# client contract (no A2A/MCP bridge), so the autonomous SequentialAgent is the natural default.
_AGENTS = {
    "testing_agent": "testing_agent.agent",
    "knowledge_gathering": "knowledge_gathering.agent",
    "test_plan_definition": "test_plan_definition.agent",
    "test_evaluation": "test_evaluation.agent",
}

# Pinned like the samples; extra_packages ships the local source (common + the agent packages).
REQUIREMENTS = [
    "google-adk[gcp,db]>=2",
    "google-cloud-aiplatform[adk,agent_engines]>=1.93",
    "google-genai>=1.9",
    "litellm>=1.0",
    "anthropic[vertex]>=1,<2",
    "google-cloud-storage>=2.16",
    "beautifulsoup4>=4.12",
    "httpx>=0.27",
    "graphifyy>=0.9,<1",
    "pydantic-settings>=2",
    "python-dotenv>=1",
]
EXTRA_PACKAGES = ["./src"]


def resolve_agent(name: str):
    """Import the agent module and return its `root_agent` (raises KeyError for an unknown name)."""
    return importlib.import_module(_AGENTS[name]).root_agent


def _cfg(args) -> dict:
    project = args.project or os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("VERTEX_PROJECT")
    location = args.location or os.environ.get("GOOGLE_CLOUD_LOCATION") or os.environ.get("VERTEX_LOCATION") or "us-central1"
    bucket = args.bucket or os.environ.get("GOOGLE_CLOUD_STORAGE_BUCKET") or os.environ.get("GCS_BUCKET")
    return {"project": project, "location": location, "bucket": bucket}


def create(args) -> None:
    import vertexai
    from vertexai import agent_engines
    from vertexai.preview.reasoning_engines import AdkApp

    cfg = _cfg(args)
    vertexai.init(project=cfg["project"], location=cfg["location"], staging_bucket=f"gs://{cfg['bucket']}")
    root = resolve_agent(args.agent)
    remote = agent_engines.create(
        AdkApp(agent=root, enable_tracing=True),
        display_name=root.name,
        requirements=REQUIREMENTS,
        extra_packages=EXTRA_PACKAGES,
        env_vars={k: os.environ[k] for k in ("VERTEX_PROJECT", "VERTEX_LOCATION", "VERTEX_MODEL",
                                             "GCS_BUCKET") if os.environ.get(k)},
    )
    print(f"Created Agent Engine: {remote.resource_name}")


def delete(args) -> None:
    import vertexai
    from vertexai import agent_engines

    cfg = _cfg(args)
    vertexai.init(project=cfg["project"], location=cfg["location"])
    agent_engines.get(args.resource_id).delete(force=True)
    print(f"Deleted {args.resource_id}")


def list_agents(args) -> None:
    import vertexai
    from vertexai import agent_engines

    cfg = _cfg(args)
    vertexai.init(project=cfg["project"], location=cfg["location"])
    for a in agent_engines.list():
        print(f"{a.resource_name}  ({a.display_name})")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Deploy a v2 ADK agent to Vertex Agent Engine.")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--create", action="store_true")
    g.add_argument("--delete", action="store_true")
    g.add_argument("--list", action="store_true")
    p.add_argument("--agent", default="testing_agent", choices=sorted(_AGENTS))
    p.add_argument("--resource-id", help="Agent Engine resource id (for --delete)")
    p.add_argument("--project")
    p.add_argument("--location")
    p.add_argument("--bucket")
    return p


def main(argv: list[str] | None = None) -> None:
    from dotenv import load_dotenv

    load_dotenv()
    args = build_parser().parse_args(argv)
    if args.create:
        create(args)
    elif args.delete:
        if not args.resource_id:
            raise SystemExit("--delete requires --resource-id")
        delete(args)
    else:
        list_agents(args)


if __name__ == "__main__":
    main()
