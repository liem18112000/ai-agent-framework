"""Test Executor root agent (ADK) — a deterministic, registry-dispatched text router (mirrors AdminRouter), NO LLM.

`_commands()` is one literal `{verb: (handler, usage)}` table. Each handler parses its `rest` and delegates
to the run ledger (`store`) / the runner. All handlers await the async store directly (it runs on the shared
Cloud SQL engine, or an in-memory fallback offline). Design: docs/RESEARCH-test-executor-agent.md.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from common.adk.router import RouterAgent
from common.monitoring import get_logger
from test_executor import ops, runner
from test_executor.store import build_store

log = get_logger("exec.router")

_Handler = Callable[[str], Awaitable[str]]  # a bound handler: (rest) -> reply


class ExecutorRouter(RouterAgent):
    async def _run_async_impl(self, ctx):
        yield self.reply(await self._dispatch(self.read(ctx).strip()))

    def _commands(self) -> dict[str, tuple[_Handler, str]]:
        return {
            "run": (self._run, "run <ctx> [env]"),
            "triage": (self._triage, "triage <ctx>"),
            "heal": (self._heal, "heal <ctx> <step_id>"),
            "report": (self._report, "report <ctx> [run_id]"),
            "environments": (self._environments, "environments <ctx>"),
        }

    async def _dispatch(self, text: str) -> str:
        cmd, _, rest = text.partition(" ")
        cmd, rest = cmd.lower(), rest.strip()
        entry = self._commands().get(cmd)
        if entry is None:
            return "Executor verbs: " + " | ".join(u for _, u in self._commands().values()) + "."
        try:
            return await entry[0](rest)
        except Exception as exc:  # noqa: BLE001 — a ledger failure returns a message, never crashes the agent
            log.warning("exec: %s failed (%s)", cmd, exc)
            return f"exec {cmd}: failed ({exc})"

    # --- commands ------------------------------------------------------------------------------------
    async def _run(self, rest: str) -> str:
        ctx, _, env = rest.partition(" ")
        if not ctx:
            return "Provide a context id: run <ctx> [env]."
        run = await runner.run_suite(build_store(), ctx, env.strip())
        # MULTI-TURN: the run is chunked; the client re-invokes `run <ctx>` until [state: done].
        state = "done" if run.get("status") == "done" else "in_progress"
        return f"[state: {state}]\n" + ops.render_run(run)

    async def _triage(self, rest: str) -> str:
        if not rest:
            return "Provide a context id: triage <ctx>."
        run = await build_store().get_run(context_id=rest)
        if not run:
            return "No run to triage — call run first."
        failures = (run.get("signals") or {}).get("failures") or []
        # finish_run already persisted the triage verdicts — reuse them; only recompute if absent (JEV/blocking).
        verdicts = run.get("triage") or await asyncio.to_thread(runner.triage, failures)
        if not verdicts:
            return f"Run {run.get('id')}: no failures to triage (status {run.get('status')})."
        return "Triage:\n" + "\n".join(f"  - {v['verdict']}: {v['message']}" for v in verdicts)

    async def _heal(self, rest: str) -> str:
        ctx, _, step = rest.partition(" ")
        if not (ctx and step.strip()):
            return "Usage: heal <ctx> <step_id>."
        return ops.render_heal(await runner.heal_step(build_store(), ctx, step.strip()))

    async def _report(self, rest: str) -> str:
        ctx, _, run_id = rest.partition(" ")
        if not ctx:
            return "Provide a context id: report <ctx> [run_id]."
        store = build_store()
        run = (await store.get_run(run_id=run_id.strip()) if run_id.strip()
               else await store.get_run(context_id=ctx))
        return ops.render_run(run)

    async def _environments(self, rest: str) -> str:
        if not rest:
            return "Provide a context id: environments <ctx>."
        return ops.render_envs(await build_store().list_environments(rest))


def build_root_agent() -> ExecutorRouter:
    return ExecutorRouter(name="test_executor")


root_agent = build_root_agent()
