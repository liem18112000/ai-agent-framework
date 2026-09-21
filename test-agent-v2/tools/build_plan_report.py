#!/usr/bin/env python
"""Generate the PLAN-PREVIEW HTML report for a context_id (deterministic, from the persisted plan).

Usage:
    python tools/build_plan_report.py <context_id> [out.html]

Reads the defined plan + decisions + brief + open questions from the memory bank (STORE_BACKEND/
GCS_BUCKET env, same as the agents) and writes one self-contained HTML page: summary, confirmed scope
decisions, methodology & test-design, scope (in/out), and open questions. The OPTIONAL step run after
`define_plan` and BEFORE `approve_plan` — publish the file with the Artifact tool so the user can
preview the plan before approving it."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from common.memory import MemoryBank
from common.report.plan_preview import build_plan_preview_html
from common.store import build_object_store


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: build_plan_report.py <context_id> [out.html]", file=sys.stderr)
        raise SystemExit(2)
    ctx = sys.argv[1]
    out = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else f"{ctx}-plan.html")
    html = build_plan_preview_html(MemoryBank(build_object_store()), ctx)
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out} ({len(html)} chars)")


if __name__ == "__main__":
    main()
