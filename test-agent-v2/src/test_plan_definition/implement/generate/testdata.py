"""Generate the test-data a plan's scenarios depend on."""

import os

from common.adk import agent_model
from common.memory.bank import _slug
from common.testplan.llm.adk import build_generator_agent, run_json_agent
from common.testplan.llm.prompts import pack_block, testdata_prompt
from common.testplan.llm.schemas import TestDataList
from common.testplan.models import FIXTURE, MOCK_DATA, TEST_ACCOUNT, TestData, TestPlan
from common.testplan.pack import PlanPack
from test_plan_definition.monitoring import get_logger

log = get_logger("llm.implement")


async def generate_test_data(plan: TestPlan, plan_pack: PlanPack, *, now: str = "",
                             detail: bool = False, model=None) -> list[TestData]:
    """Detailed heuristic by default; opt into the TestDataGen ``LlmAgent`` per-call with
    ``detail``/``TPD_LLM_DETAIL`` (kept off the I3 default path).

    The generator run is inlined here (its sole caller): the stable context pack is the agent's cached
    system instruction (``pack_block``) and the TASK is the user turn (``testdata_prompt``, so the pack
    isn't duplicated), matching the other implement generators."""
    if detail or os.environ.get("TPD_LLM_DETAIL"):
        model = model or agent_model(max_tokens=6000)
        if model is not None:
            summary = plan_pack.summary_text()
            agent = build_generator_agent(name="tpd_testdata_gen", system=pack_block(summary),
                                          output_schema=TestDataList, output_key="tpd_test_data",
                                          model=model)
            data = await run_json_agent(agent, output_key="tpd_test_data",
                                        user=testdata_prompt(plan, summary, include_context=False))
            if not data:
                log.warning("could not parse test-data output; falling back to heuristic")
            elif td := TestDataList(**data).to_test_data(plan, now):
                return td
    return heuristic_test_data(plan, plan_pack, now=now)


def heuristic_test_data(plan: TestPlan, plan_pack: PlanPack, *, now: str = "") -> list[TestData]:
    ctx = plan.context_id
    method = plan.methodology[0] if plan.methodology else "api"
    out = [TestData(
        id=f"test-data:{ctx}:account", kind=TEST_ACCOUNT, plan_id=plan.id,
        spec={
            "purpose": "authenticated caller for the API tests",
            "role": "standard",
            "tenant": "<test-tenant>",
            "auth": "bearer token",
            "permissions": ["read", "write"],
        },
        source_refs=plan.source_refs[:1], created_at=now,
    )]
    out += [TestData(
        id=f"test-data:{ctx}:mock:{_slug(n.id)}", kind=MOCK_DATA, plan_id=plan.id,
        spec={
            "entity": n.title,
            "from_note": n.id,
            "fields": {"id": "<generated>", "status": "<expected>"},
            "notes": "representative valid record; mutate fields for the negative/boundary cases",
        },
        source_refs=[n.id], created_at=now,
    ) for n in plan_pack.pack.grounded]  # Q2: one mock per grounded note — no cap
    if method == "api":
        out.append(TestData(
            id=f"test-data:{ctx}:fixture", kind=FIXTURE, plan_id=plan.id,
            spec={"kind": "request-payload", "format": "json", "purpose": "valid request-body baseline"},
            source_refs=plan.source_refs[:1], created_at=now,
        ))
    return out
