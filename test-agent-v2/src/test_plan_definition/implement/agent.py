"""ImplementOrchestrator — the interactive implement stage (Q3/Q4): a parent BaseAgent that nests two
sub-agents, `interrogate` (implement/interrogate) then `generate` (implement/generate)."""

from __future__ import annotations

from google.adk.agents import BaseAgent

from common.memory.factory import build_bank


class ImplementOrchestrator(BaseAgent):
    """Runs the interrogation until the design is confirmed, then chains straight into generation on
    that turn. `interrogate` (case-design/data-design/step-oracle) → `generate` (artifact generation)."""

    interrogate: BaseAgent
    generate: BaseAgent

    async def _run_async_impl(self, ctx):
        from common.testplan import memory as store

        bank = build_bank()
        ctx_id = (ctx.session.state or {}).get("io_pack_ctx") or ctx.session.id
        if not (store.read_implement_state(bank, ctx_id) or {}).get("done"):
            async for ev in self.interrogate.run_async(ctx):  # start or continue the interrogation
                yield ev
            if not (store.read_implement_state(bank, ctx_id) or {}).get("done"):
                return  # still interrogating — waiting for the next answer turn
        async for ev in self.generate.run_async(ctx):  # design confirmed → generate artifacts
            yield ev


def build_implement_agent(name: str = "implement") -> ImplementOrchestrator:
    from test_plan_definition.implement.generate.agent import ImplementAgent
    from test_plan_definition.implement.interrogate.agent import build_interrogate_agent

    interrogate, generate = build_interrogate_agent(), ImplementAgent(name="generate")
    return ImplementOrchestrator(name=name, interrogate=interrogate, generate=generate,
                                 sub_agents=[interrogate, generate])
