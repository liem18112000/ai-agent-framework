#!/usr/bin/env python
"""Generate the knowledge-PREVIEW HTML report for a context_id (deterministic, from the persisted pack).

Usage:
    python tools/build_knowledge_report.py <context_id> [out.html]

Reads the gathered pack + understanding + open questions (+ optional benchmark) from the memory bank
(STORE_BACKEND/GCS_BUCKET env, same as the agents) and writes one self-contained HTML page: understanding,
knowledge map, key concepts (with diagrams), gaps & open questions, sources, and pack quality (PQS).
The OPTIONAL step run after `refine` and before approve — publish the file with the Artifact tool so the
user can preview the knowledge before approving the pack."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from common.memory import MemoryBank
from common.report.knowledge import build_knowledge_report_html
from common.store import build_object_store


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: build_knowledge_report.py <context_id> [out.html]", file=sys.stderr)
        raise SystemExit(2)
    ctx = sys.argv[1]
    out = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else f"{ctx}-knowledge.html")
    html = build_knowledge_report_html(MemoryBank(build_object_store()), ctx)
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out} ({len(html)} chars)")


if __name__ == "__main__":
    main()
