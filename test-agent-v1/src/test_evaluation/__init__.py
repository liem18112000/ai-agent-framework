"""Test-Evaluation Agent (test_evaluation) — the third Testing-Agent service.

Scores both upstream artifacts, from the shared GCS memory bank, without importing either scored
agent (reads their persisted output as dicts / via common.memory, run-scoped like refine):
  - evaluate_pack — the KGA pack (ADK trajectory + RAGAS retrieval/generation) -> Pack Quality Score.
  - evaluate_plan — the TPD plan + suite (scope/coverage/oracle/fault + brief groundedness) ->
    Test-Plan Score.
The A2A ASGI app is `test_evaluation.server:app`. See docs/RESEARCH-kga-evaluation-adk-ragas.md and
docs/RESEARCH-tpd-evaluation-adk-testsuite.md.
"""

__version__ = "0.1.0"
