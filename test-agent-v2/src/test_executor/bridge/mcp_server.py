"""Test Executor MCP tool definitions — the execution stage on the single MCP gateway.

Five thin forwarders over the executor A2A agent. The pipeline seam is AFTER get_scenarios:
`… → implement_plan → get_scenarios → run_suite → [triage_run / heal_step] → get_run_report`
(optional and read-model-friendly, like evaluate_plan). Tool names are globally unique across the gateway.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from common.bridge import BridgeSession


def register_tools(mcp: MCPServer, session: BridgeSession) -> dict:
    """Register the execution-stage tools on `mcp`, bound to `session`; return {name: fn}."""

    @mcp.tool()
    async def run_suite(context_id: str, env: str = "") -> str:
        """[EXECUTION] Run the scenarios implemented for this run against a target environment and
        record the run to the shared ledger. Call it AFTER get_scenarios. `env` names the target
        (e.g. dev / staging / a Cloud Run revision / a tenant); omit it for the default environment —
        a new environment is registered on first sight.

        MULTI-TURN: the run is chunked so one call stays under the MCP idle timeout. If the reply
        starts `[state: in_progress]`, call run_suite(context_id) again (no new args) to run the next
        chunk — repeat until `[state: done]`, then read the outcome with get_run_report.

        Execution is opt-in via EXEC_RUNNER=auto (routes each scenario to the engine that fits its
        nature); the default is a one-shot stub that records the env + run row."""
        return (await session.ask(f"run {context_id} {env}".strip(), context_id=context_id)).text

    @mcp.tool()
    async def triage_run(context_id: str) -> str:
        """[EXECUTION] Classify the failures of the latest run for this context into
        Bug / Heal / Flaky / Environment (heuristic today; the JEV decision cascade fronts it later).
        A real bug defaults loud — it is never silently healed or quarantined."""
        return (await session.ask(f"triage {context_id}", context_id=context_id)).text

    @mcp.tool()
    async def heal_step(context_id: str, step_id: str) -> str:
        """[EXECUTION] Propose a locator/wait/data patch for one failing step and re-run it. Every heal
        is surfaced for a human Yes/No — never a silent retarget (that can mask a real regression).
        NOTE: slice 0 returns guidance only; the real replay+patch healer is the next slice."""
        return (await session.ask(f"heal {context_id} {step_id}", context_id=context_id)).text

    @mcp.tool()
    async def get_run_report(context_id: str, run_id: str = "") -> str:
        """[EXECUTION] Read the persisted run report — status, environment, summary counts, real
        signals, and per-failure triage. Defaults to the latest run for the context; pass `run_id` for
        a specific one. Read-only."""
        return (await session.ask(f"report {context_id} {run_id}".strip(), context_id=context_id)).text

    @mcp.tool()
    async def list_environments(context_id: str) -> str:
        """[EXECUTION] List the environments this context has been tested against and when each was
        last seen — the basis for differential (cross-environment) comparison."""
        return (await session.ask(f"environments {context_id}", context_id=context_id)).text

    return {"run_suite": run_suite, "triage_run": triage_run, "heal_step": heal_step,
            "get_run_report": get_run_report, "list_environments": list_environments}
