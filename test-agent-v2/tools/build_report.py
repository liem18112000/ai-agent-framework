#!/usr/bin/env python
"""Generate the enriched HTML test report for a context_id (deterministic, from the persisted run).

Usage:
    python tools/build_report.py <context_id> [out.html]

Reads scenarios/steps/plan/test-data/benchmark from the memory bank (STORE_BACKEND/GCS_BUCKET env, same
as the agents) and writes one self-contained HTML page with the Scenarios / Feature files / Test data /
Benchmark / Test-case-workflow tabs. Publish the file as the deliverable artifact."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from common.memory import MemoryBank  # noqa: E402
from common.store import build_object_store  # noqa: E402
from common.testplan.report import build_report_html  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: build_report.py <context_id> [out.html]", file=sys.stderr)
        raise SystemExit(2)
    ctx = sys.argv[1]
    out = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else f"{ctx}-report.html")
    html = build_report_html(MemoryBank(build_object_store()), ctx)
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out} ({len(html)} chars)")


if __name__ == "__main__":
    main()
