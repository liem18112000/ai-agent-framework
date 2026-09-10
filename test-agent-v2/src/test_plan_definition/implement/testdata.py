"""Generate the test-data a plan's scenarios depend on."""

import os

from common.memory.bank import _slug
from common.testplan.models import FIXTURE, MOCK_DATA, TEST_ACCOUNT, TestData, TestPlan
from common.testplan.pack import PlanPack


async def generate_test_data(plan: TestPlan, plan_pack: PlanPack, *, now: str = "",
                             detail: bool = False, model=None) -> list[TestData]:
    """Detailed heuristic by default; opt into the TestDataGen ``LlmAgent`` per-call with
    ``detail``/``TPD_LLM_DETAIL`` (kept off the I3 default path)."""
    if detail or os.environ.get("TPD_LLM_DETAIL"):
        from test_plan_definition.implement.llm import claude_test_data

        td = await claude_test_data(plan, plan_pack, now=now, model=model)
        if td:
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
