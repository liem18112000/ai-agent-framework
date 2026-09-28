"""AssuredScenarioAgent — the ADK ``BaseAgent`` face of the P4 assured loop, in its own sub-agent
package (a peer of `interrogate` / `generate` under the ImplementOrchestrator). The deterministic
loop lives in ``loop.py``; this agent reconstructs the loop's inputs from the bank, runs it, persists
the winning scenarios, and reports the ``AssuredReport`` as an observable event + session state_delta."""

from __future__ import annotations

from dataclasses import asdict

from google.adk.agents import BaseAgent

from common.adk.events import now, text_event
from common.memory.factory import build_bank
from common.testplan import memory as store
from common.testplan.models import CONFIRMED
from test_plan_definition.implement.assured.loop import run_assured_scenarios


class AssuredScenarioAgent(BaseAgent):
    """Reconstructs the plan / pack / test-data from the bank (mirroring ``ImplementAgent``), runs the
    shared ``run_assured_scenarios`` engine, persists the winning scenarios, and reports the
    ``AssuredReport`` both as a summary event and a session ``state_delta`` (``tpd_assured``) so the
    loop is observable in the ADK stream. Opt-in (``TPD_ASSURED``), bounds, and GCS resume live in the
    engine — unchanged; this agent adds no new behavior."""

    async def _run_async_impl(self, ctx):
        from common.testplan.pack import load_plan_pack
        from test_plan_definition.implement.generate.testdata import generate_test_data

        bank = build_bank()
        ctx_id = (ctx.session.state or {}).get("io_pack_ctx") or ctx.session.id
        plan = store.read_plan(bank, ctx_id)
        if plan is None or plan.status != CONFIRMED:
            yield text_event(self.name, f"No confirmed plan for {ctx_id}; define + approve it first.")
            return
        plan_pack = load_plan_pack(bank, ctx_id)
        stamp = now()
        # test-data is an input to the loop; reuse a persisted set or derive one heuristically (no LLM).
        test_data = store.read_test_data(bank, ctx_id) or await generate_test_data(
            plan, plan_pack, now=stamp)
        scenarios, report, _ = await run_assured_scenarios(  # observable face runs to completion
            bank, ctx_id, plan, plan_pack, test_data, now=stamp)
        store.write_scenarios(bank, ctx_id, scenarios, [])
        verdict = "PASS" if report.accepted else "BELOW BAR"
        yield text_event(
            self.name,
            f"Assured loop: {verdict} — {len(scenarios)} scenarios over {report.rounds} round(s), "
            f"score {report.final_score:.2f} vs threshold {report.threshold:.2f}. {report.note}",
            state_delta={"tpd_assured": asdict(report)})


def build_assured_agent(name: str = "assured") -> AssuredScenarioAgent:
    """Build the assured-loop ADK agent — the observable ``BaseAgent`` face of the engine."""
    return AssuredScenarioAgent(name=name)
